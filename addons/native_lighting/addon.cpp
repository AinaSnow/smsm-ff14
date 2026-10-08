#include "diagnostic.hpp"
#include <reshade.hpp>
#include <memory>
#include <mutex>
#ifdef SMSM_NATIVE_AMBIENT_EXPERIMENT
#include "ambient_bridge.hpp"
#include "native_ambient_bytecode.hpp"
#endif
#ifdef SMSM_NATIVE_COVERAGE
#include "coverage_bridge.hpp"
#include "native_coverage_bytecode.hpp"
#endif

using namespace reshade::api;
namespace {
struct State {
    smsm::Diagnostic diagnostic;
    uint64_t swapchain = 0;
#ifdef SMSM_NATIVE_AMBIENT_EXPERIMENT
    smsm::AmbientBridge ambient;
#endif
#ifdef SMSM_NATIVE_COVERAGE
    smsm::CoverageBridge coverage;
#endif
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
#ifdef SMSM_NATIVE_AMBIENT_EXPERIMENT
    if(it->second->ambient.internal)return;
#endif
#ifdef SMSM_NATIVE_COVERAGE
    if(it->second->coverage.internal)return;
#endif
    try { f(*it->second); }
    catch (const std::exception &e) {
        it->second->diagnostic.set_enabled(false);
        it->second->diagnostic.recording=it->second->diagnostic.waiting=false;
        it->second->diagnostic.draws.clear();
#ifdef SMSM_NATIVE_AMBIENT_EXPERIMENT
        it->second->ambient.disable();
#endif
#ifdef SMSM_NATIVE_COVERAGE
        it->second->coverage.disable();
#endif
        reshade::log::message(reshade::log::level::error,e.what());
    }
}
void init_device(device *dev) {
    if (dev->get_api()!=device_api::d3d11) return;
    std::lock_guard<std::recursive_mutex> lock(mutex);
    try {
        states.emplace(dev,std::make_unique<State>(output_path()));
#ifdef SMSM_NATIVE_AMBIENT_EXPERIMENT
        states.at(dev)->ambient.initialize(reinterpret_cast<ID3D11Device *>(dev->get_native()),native_ambient_bytecode,sizeof(native_ambient_bytecode));
#endif
#ifdef SMSM_NATIVE_COVERAGE
        states.at(dev)->coverage.initialize(reinterpret_cast<ID3D11Device *>(dev->get_native()),native_coverage_bytecode,sizeof(native_coverage_bytecode));
#endif
    }
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
void destroy_resource(device *dev,resource r) { guarded(dev,[&](State &s){s.diagnostic.destroy_resource(r.handle);
#ifdef SMSM_NATIVE_AMBIENT_EXPERIMENT
    s.ambient.note_write(r.handle);
#endif
}); }
void note(device *dev,resource r,const char *kind) { guarded(dev,[&](State &s){s.diagnostic.write(r.handle,kind);
#ifdef SMSM_NATIVE_AMBIENT_EXPERIMENT
    s.ambient.note_write(r.handle);
#endif
}); }
bool update_buffer(device *dev,const void *,resource r,uint64_t,uint64_t) { note(dev,r,"update_buffer_intent"); return false; }
bool update_texture(device *dev,const subresource_data &,resource r,uint32_t,const subresource_box *) { note(dev,r,"update_texture_intent"); return false; }
void map_buffer(device *dev,resource r,uint64_t,uint64_t,map_access access,void **) {
    if (access!=map_access::read_only) note(dev,r,"map_buffer_write_access");
}
void map_texture(device *dev,resource r,uint32_t,const subresource_box *,map_access access,subresource_data *) {
    if (access!=map_access::read_only) note(dev,r,"map_texture_write_access");
}
bool copy_resource(command_list *cmd,resource source,resource dest) {
    guarded(cmd->get_device(),[&](State &s){s.diagnostic.copy_write(dest.handle,source.handle,"copy_resource_intent");
#ifdef SMSM_NATIVE_AMBIENT_EXPERIMENT
        s.ambient.note_write(dest.handle);
#endif
    }); return false;
}
bool copy_buffer(command_list *cmd,resource,uint64_t,resource r,uint64_t,uint64_t) { note(cmd->get_device(),r,"copy_buffer_intent"); return false; }
bool copy_texture(command_list *cmd,resource source,uint32_t src_sub,const subresource_box *,resource dest,uint32_t dst_sub,const subresource_box *,filter_mode) {
    guarded(cmd->get_device(),[&](State &s){s.diagnostic.copy_write(dest.handle,source.handle,"copy_texture_intent",src_sub,dst_sub);
#ifdef SMSM_NATIVE_AMBIENT_EXPERIMENT
        s.ambient.note_write(dest.handle);
#endif
    }); return false;
}
bool resolve(command_list *cmd,resource,uint32_t,const subresource_box *,resource r,uint32_t,uint32_t,uint32_t,uint32_t,format) { note(cmd->get_device(),r,"resolve_intent"); return false; }
bool clear_rt(command_list *cmd,resource_view view,const float[4],uint32_t,const rect *) {
    note(cmd->get_device(),cmd->get_device()->get_resource_from_view(view),"clear_render_target_intent"); return false;
}
bool clear_depth(command_list *cmd,resource_view view,const float *,const uint8_t *,uint32_t,const rect *) {
    note(cmd->get_device(),cmd->get_device()->get_resource_from_view(view),"clear_depth_intent"); return false;
}
template<class F> bool native_draw(command_list *cmd,const char *kind,uint32_t count,uint32_t instances,F call) {
    (void)call;
    bool replaced=false;
    guarded(cmd->get_device(),[&](State &s){
        auto *ctx=reinterpret_cast<ID3D11DeviceContext *>(cmd->get_native());
        s.diagnostic.before_draw(ctx,kind,count,instances);
#ifdef SMSM_NATIVE_AMBIENT_EXPERIMENT
#ifdef SMSM_NATIVE_COVERAGE
        if(s.coverage.enabled()) {
            smsm::ComPtr<ID3D11PixelShader> ps;ctx->PSGetShader(&ps,nullptr,nullptr);
            auto identity=s.diagnostic.shaders.find(reinterpret_cast<uint64_t>(ps.Get()));
            if(identity!=s.diagnostic.shaders.end() && identity->second.first==smsm::game_targets[1].migoto && count!=UINT32_MAX)
                replaced=s.coverage.draw(ctx,GetTickCount64(),[&]{call(ctx);});
            return;
        }
#endif
        if(!s.ambient.enabled())return;
        smsm::ComPtr<ID3D11PixelShader> ps;ctx->PSGetShader(&ps,nullptr,nullptr);
        auto identity=s.diagnostic.shaders.find(reinterpret_cast<uint64_t>(ps.Get()));
        if(identity==s.diagnostic.shaders.end())return;
        if(identity->second.first==smsm::game_targets[0].migoto)s.ambient.capture_source(ctx);
        else if(identity->second.first==smsm::game_targets[1].migoto && count!=UINT32_MAX)
            replaced=s.ambient.draw(ctx,[&]{call(ctx);});
#endif
    });
    return replaced;
}
bool draw(command_list *cmd,uint32_t count,uint32_t instances,uint32_t first,uint32_t first_instance) {
    return native_draw(cmd,"draw",count,instances,[&](ID3D11DeviceContext *ctx){
        if(instances==1 && first_instance==0)ctx->Draw(count,first);else ctx->DrawInstanced(count,instances,first,first_instance);
    });
}
bool draw_indexed(command_list *cmd,uint32_t count,uint32_t instances,uint32_t first,int32_t offset,uint32_t first_instance) {
    return native_draw(cmd,"draw_indexed",count,instances,[&](ID3D11DeviceContext *ctx){
        if(instances==1 && first_instance==0)ctx->DrawIndexed(count,first,offset);else ctx->DrawIndexedInstanced(count,instances,first,offset,first_instance);
    });
}
void present(command_queue *queue,swapchain *sc,const rect *,const rect *,uint32_t,const rect *) {
    guarded(queue->get_device(),[&](State &s) {
        if (!s.swapchain) s.swapchain=sc->get_native();
        if (s.swapchain!=sc->get_native()) return;
        auto &d=s.diagnostic;
        auto *context=reinterpret_cast<ID3D11DeviceContext *>(queue->get_immediate_command_list()->get_native());
        d.present(context);
#ifdef SMSM_NATIVE_AMBIENT_EXPERIMENT
        s.ambient.reset_frame();
        auto write_status=[&] {
            smsm::Json report;report.fields["enabled"]=s.ambient.enabled()?"true":"false";
            report.num("copies",s.ambient.copies);report.num("overrides",s.ambient.overrides);report.num("fallbacks",s.ambient.fallbacks);
#ifdef SMSM_NATIVE_COVERAGE
            report.fields["coverage_enabled"]=s.coverage.enabled()?"true":"false";
            report.num("coverage_draws",s.coverage.draws);report.num("coverage_fallbacks",s.coverage.fallbacks);
#endif
            std::ofstream output(d.root/"ambient-status.json");output<<report.str()<<'\n';
        };
#ifdef SMSM_NATIVE_COVERAGE
        if(s.coverage.expire(GetTickCount64()))write_status();
#endif
        const auto ambient_command=d.root/"ambient-command.txt";
        if(GetFileAttributesW(ambient_command.c_str())!=INVALID_FILE_ATTRIBUTES) {
            std::ifstream input(ambient_command);char action[64]={};input.getline(action,sizeof(action));input.close();
            if(!smsm::fs::remove(ambient_command))throw std::runtime_error("ambient_command_consume_failed");
            const std::string value=action;
#ifdef SMSM_NATIVE_COVERAGE
            if(value!="status")s.coverage.disable();
            if(value=="coverage") {d.stop();s.ambient.disable();s.coverage.enable(GetTickCount64());}
            else
#endif
            if(value=="on" || value=="half") {d.stop();s.ambient.set_strength(context,value=="on"?1.f:.5f);}
            else if(value=="off")s.ambient.disable();
            else if(value!="status")throw std::runtime_error("unknown ambient command");
            write_status();
        }
#endif
        // One manually submitted command is consumed at a frame boundary. No persistent auto-capture mode.
        const auto command=d.root.parent_path()/"SMSM-native-command.txt";
        if (GetFileAttributesW(command.c_str())!=INVALID_FILE_ATTRIBUTES) {
            std::ifstream in(command); std::string action; std::getline(in,action); in.close();
            if (!smsm::fs::remove(command)) throw std::runtime_error("command_consume_failed");
#ifdef SMSM_NATIVE_AMBIENT_EXPERIMENT
            if(action=="enable" || action=="capture")s.ambient.disable();
#endif
#ifdef SMSM_NATIVE_COVERAGE
            s.coverage.disable();
#endif
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
        if (s.swapchain==sc->get_native()) {s.diagnostic.stop(); s.swapchain=0;
#ifdef SMSM_NATIVE_AMBIENT_EXPERIMENT
            s.ambient.disable();
#endif
#ifdef SMSM_NATIVE_COVERAGE
            s.coverage.disable();
#endif
        }
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
#ifdef SMSM_NATIVE_AMBIENT_EXPERIMENT
            s.ambient.disable();
#endif
#ifdef SMSM_NATIVE_COVERAGE
            s.coverage.disable();
#endif
            if (d.enabled) d.stop(); else d.set_enabled(true);
            reshade::log::message(reshade::log::level::info,d.enabled ? "SMSM diagnostic enabled; F8 captures next frame" : "SMSM diagnostic stopped");
        }
        if (runtime->is_key_pressed(VK_F8)) {
            const bool armed=d.arm();
            reshade::log::message(reshade::log::level::info,armed ? "SMSM capture armed" : "SMSM capture rejected: disabled or busy");
        }
    });
}
void execute_secondary(command_list *cmd,command_list *) {
    (void)cmd;
#ifdef SMSM_NATIVE_AMBIENT_EXPERIMENT
    guarded(cmd->get_device(),[](State &s){s.ambient.invalidate();});
#endif
}
}
extern "C" __declspec(dllexport) const char *NAME="SMSM Native Lighting Diagnostic";
#ifdef SMSM_NATIVE_COVERAGE
extern "C" __declspec(dllexport) const char *DESCRIPTION="Default-off native ambient experiment and 10-second exact hair-variant coverage marker. F7 stops experiments and toggles resource audit.";
#else
extern "C" __declspec(dllexport) const char *DESCRIPTION="Default-off read-only D3D11 native resource audit. F7 enable/stop; F8 capture one following frame.";
#endif
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
        EVENT(execute_secondary_command_list,execute_secondary);
        EVENT(destroy_swapchain,destroy_swapchain); EVENT(reshade_present,controls);
#undef EVENT
    } else if (reason==DLL_PROCESS_DETACH) reshade::unregister_addon(module);
    return TRUE;
}
