#include "diagnostic.hpp"
#include <reshade.hpp>
#include <memory>
#include <mutex>

using namespace reshade::api;
namespace {
struct State {
    smsm::Diagnostic diagnostic;
    uint64_t swapchain = 0;
    explicit State(const smsm::fs::path &path) : diagnostic(path) {}
};
std::recursive_mutex mutex;
std::map<device *, std::unique_ptr<State>> states;
smsm::fs::path output_path() {
    wchar_t path[32768]; const DWORD n=GetModuleFileNameW(nullptr,path,32768);
    if (!n || n >= 32768) throw std::runtime_error("executable_path_unavailable");
    return smsm::fs::path(path).parent_path() / "SMSM-native-captures";
}
template<class F> void guarded(device *dev, F &&f) noexcept {
    std::lock_guard<std::recursive_mutex> lock(mutex);
    auto it=states.find(dev); if (it==states.end() || it->second->diagnostic.internal) return;
    try { f(*it->second); }
    catch (const std::exception &e) {
        it->second->diagnostic.set_enabled(false);
        it->second->diagnostic.recording=it->second->diagnostic.waiting=false;
        it->second->diagnostic.draws.clear();
        reshade::log::message(reshade::log::level::error,e.what());
    }
}
void init_device(device *dev) {
    if (dev->get_api()!=device_api::d3d11) return;
    std::lock_guard<std::recursive_mutex> lock(mutex);
    try { states.emplace(dev,std::make_unique<State>(output_path())); }
    catch (const std::exception &e) { reshade::log::message(reshade::log::level::error,e.what()); }
}
void destroy_device(device *dev) {
    guarded(dev,[](State &s){s.diagnostic.stop();});
    std::lock_guard<std::recursive_mutex> lock(mutex); states.erase(dev);
}
void init_pipeline(device *dev,pipeline_layout,uint32_t n,const pipeline_subobject *objects,pipeline p) {
    guarded(dev,[&](State &s) {
        for (uint32_t i=0;i<n;++i)
            if (objects[i].type==pipeline_subobject_type::pixel_shader || objects[i].type==pipeline_subobject_type::vertex_shader) {
                const auto &desc=*static_cast<const shader_desc *>(objects[i].data);
                if (objects[i].count==1 && desc.code && desc.code_size) s.diagnostic.init_shader(p.handle,desc.code,desc.code_size);
            }
    });
}
void destroy_pipeline(device *dev,pipeline p) { guarded(dev,[&](State &s){s.diagnostic.shaders.erase(p.handle);}); }
void init_resource(device *dev,const resource_desc &,const subresource_data *data,resource_usage,resource r) {
    guarded(dev,[&](State &s){s.diagnostic.init_resource(r.handle,data!=nullptr);});
}
void destroy_resource(device *dev,resource r) { guarded(dev,[&](State &s){s.diagnostic.destroy_resource(r.handle);}); }
void note(device *dev,resource r,const char *kind) { guarded(dev,[&](State &s){s.diagnostic.write(r.handle,kind);}); }
bool update_buffer(device *dev,const void *,resource r,uint64_t,uint64_t) { note(dev,r,"update_buffer_intent"); return false; }
bool update_texture(device *dev,const subresource_data &,resource r,uint32_t,const subresource_box *) { note(dev,r,"update_texture_intent"); return false; }
void map_buffer(device *dev,resource r,uint64_t,uint64_t,map_access access,void **) {
    if (access!=map_access::read_only) note(dev,r,"map_buffer_write_access");
}
void map_texture(device *dev,resource r,uint32_t,const subresource_box *,map_access access,subresource_data *) {
    if (access!=map_access::read_only) note(dev,r,"map_texture_write_access");
}
bool copy_resource(command_list *cmd,resource source,resource dest) {
    guarded(cmd->get_device(),[&](State &s){s.diagnostic.copy_write(dest.handle,source.handle,"copy_resource_intent");}); return false;
}
bool copy_buffer(command_list *cmd,resource,uint64_t,resource r,uint64_t,uint64_t) { note(cmd->get_device(),r,"copy_buffer_intent"); return false; }
bool copy_texture(command_list *cmd,resource source,uint32_t src_sub,const subresource_box *,resource dest,uint32_t dst_sub,const subresource_box *,filter_mode) {
    guarded(cmd->get_device(),[&](State &s){s.diagnostic.copy_write(dest.handle,source.handle,"copy_texture_intent",src_sub,dst_sub);}); return false;
}
bool resolve(command_list *cmd,resource,uint32_t,const subresource_box *,resource r,uint32_t,uint32_t,uint32_t,uint32_t,format) { note(cmd->get_device(),r,"resolve_intent"); return false; }
bool clear_rt(command_list *cmd,resource_view view,const float[4],uint32_t,const rect *) {
    note(cmd->get_device(),cmd->get_device()->get_resource_from_view(view),"clear_render_target_intent"); return false;
}
bool clear_depth(command_list *cmd,resource_view view,const float *,const uint8_t *,uint32_t,const rect *) {
    note(cmd->get_device(),cmd->get_device()->get_resource_from_view(view),"clear_depth_intent"); return false;
}
bool draw(command_list *cmd,uint32_t count,uint32_t instances,uint32_t,uint32_t) {
    guarded(cmd->get_device(),[&](State &s){s.diagnostic.before_draw(reinterpret_cast<ID3D11DeviceContext *>(cmd->get_native()),"draw",count,instances);});
    return false; // The application's draw always executes, including on capture failures.
}
bool draw_indexed(command_list *cmd,uint32_t count,uint32_t instances,uint32_t,int32_t,uint32_t) {
    guarded(cmd->get_device(),[&](State &s){s.diagnostic.before_draw(reinterpret_cast<ID3D11DeviceContext *>(cmd->get_native()),"draw_indexed",count,instances);});
    return false;
}
void present(command_queue *queue,swapchain *sc,const rect *,const rect *,uint32_t,const rect *) {
    guarded(queue->get_device(),[&](State &s) {
        if (!s.swapchain) s.swapchain=sc->get_native();
        if (s.swapchain!=sc->get_native()) return;
        auto &d=s.diagnostic;
        d.present(reinterpret_cast<ID3D11DeviceContext *>(queue->get_immediate_command_list()->get_native()));
        // One manually submitted command is consumed at a frame boundary. No persistent auto-capture mode.
        const auto command=d.root.parent_path()/"SMSM-native-command.txt";
        if (GetFileAttributesW(command.c_str())!=INVALID_FILE_ATTRIBUTES) {
            std::ifstream in(command); std::string action; std::getline(in,action); in.close();
            if (!smsm::fs::remove(command)) throw std::runtime_error("command_consume_failed");
            if (action=="enable") d.set_enabled(true);
            else if (action=="stop") d.stop();
            else if (action=="capture") {
                if (!d.arm()) reshade::log::message(reshade::log::level::warning,"SMSM capture rejected: disabled or busy");
            } else reshade::log::message(reshade::log::level::warning,"SMSM unknown command rejected");
        }
    });
}
void destroy_swapchain(swapchain *sc,bool) {
    guarded(sc->get_device(),[&](State &s){
        if (s.swapchain==sc->get_native()) {s.diagnostic.stop(); s.swapchain=0;}
    });
}
void controls(effect_runtime *runtime) {
    DWORD owner=0; GetWindowThreadProcessId(GetForegroundWindow(),&owner);
    if (owner!=GetCurrentProcessId()) return;
    guarded(runtime->get_device(),[&](State &s) {
        // Only the chosen Present stream may arm its next frame.
        if (s.swapchain!=runtime->get_native()) return;
        auto &d=s.diagnostic;
        if (runtime->is_key_pressed(VK_F7)) {
            if (d.enabled) d.stop(); else d.set_enabled(true);
            reshade::log::message(reshade::log::level::info,d.enabled ? "SMSM diagnostic enabled; F8 captures next frame" : "SMSM diagnostic stopped");
        }
        if (runtime->is_key_pressed(VK_F8)) {
            const bool armed=d.arm();
            reshade::log::message(reshade::log::level::info,armed ? "SMSM capture armed" : "SMSM capture rejected: disabled or busy");
        }
    });
}
}
extern "C" __declspec(dllexport) const char *NAME="SMSM Native Lighting Diagnostic";
extern "C" __declspec(dllexport) const char *DESCRIPTION="Default-off read-only D3D11 native resource audit. F7 enable/stop; F8 capture one following frame.";
BOOL APIENTRY DllMain(HMODULE module,DWORD reason,LPVOID) {
    if (reason==DLL_PROCESS_ATTACH) {
        if (!reshade::register_addon(module)) return FALSE;
#define EVENT(name,fn) reshade::register_event<reshade::addon_event::name>(fn)
        EVENT(init_device,init_device); EVENT(destroy_device,destroy_device);
        EVENT(init_pipeline,init_pipeline); EVENT(destroy_pipeline,destroy_pipeline);
        EVENT(init_resource,init_resource); EVENT(destroy_resource,destroy_resource);
        EVENT(update_buffer_region,update_buffer); EVENT(update_texture_region,update_texture);
        EVENT(map_buffer_region,map_buffer); EVENT(map_texture_region,map_texture);
        EVENT(copy_resource,copy_resource); EVENT(copy_buffer_region,copy_buffer); EVENT(copy_texture_region,copy_texture);
        EVENT(resolve_texture_region,resolve); EVENT(clear_render_target_view,clear_rt); EVENT(clear_depth_stencil_view,clear_depth);
        EVENT(draw,draw); EVENT(draw_indexed,draw_indexed); EVENT(present,present);
        EVENT(destroy_swapchain,destroy_swapchain); EVENT(reshade_present,controls);
#undef EVENT
    } else if (reason==DLL_PROCESS_DETACH) reshade::unregister_addon(module);
    return TRUE;
}
