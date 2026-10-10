// Isolated reproduction of Dalamud 15.0.3.6's composition viewport path.
// No injection into FF14. Each runtime runs in its own disposable process.
#include <windows.h>
#include <d3d11.h>
#include <dxgi1_4.h>
#include <dcomp.h>
#include <wrl/client.h>
#include <cstdio>
using Microsoft::WRL::ComPtr;
static void check(const char* step, HRESULT hr) {
    printf("%s: 0x%08lx\n", step, (unsigned long)hr); fflush(stdout);
    if (FAILED(hr)) ExitProcess(2);
}
int wmain(int argc, wchar_t** argv) {
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    if (argc != 2 && argc != 3) return 1;
    HMODULE runtime = LoadLibraryW(argv[1]);
    if (!runtime) return 3;
    auto create = reinterpret_cast<decltype(&D3D11CreateDevice)>(GetProcAddress(runtime, "D3D11CreateDevice"));
    if (!create) return 4;
    ComPtr<ID3D11Device> device;
    ComPtr<ID3D11DeviceContext> context;
    D3D_FEATURE_LEVEL level;
    check("D3D11CreateDevice", create(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
        D3D11_CREATE_DEVICE_BGRA_SUPPORT, nullptr, 0, D3D11_SDK_VERSION, &device, &level, &context));
    ComPtr<IDXGIFactory4> factory;
    check("CreateDXGIFactory1", CreateDXGIFactory1(IID_PPV_ARGS(&factory)));
    if (argc == 3 && wcscmp(argv[2], L"main-only") == 0) {
        HWND window = CreateWindowExW(0, L"STATIC", L"SMSM isolated compatibility test",
            WS_OVERLAPPEDWINDOW, 0, 0, 32, 32, nullptr, nullptr, GetModuleHandleW(nullptr), nullptr);
        if (!window) return 5; // Hidden window: never show it or focus the game.
        DXGI_SWAP_CHAIN_DESC desc = {};
        desc.BufferDesc.Width = desc.BufferDesc.Height = 16;
        desc.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        desc.SampleDesc.Count = 1; desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
        desc.BufferCount = 2; desc.OutputWindow = window; desc.Windowed = TRUE;
        desc.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;
        ComPtr<IDXGISwapChain> mainSwap;
        check("CreateSwapChain (main)", factory->CreateSwapChain(device.Get(), &desc, &mainSwap));
        ComPtr<ID3D11Texture2D> backBuffer;
        check("GetBuffer", mainSwap->GetBuffer(0, IID_PPV_ARGS(&backBuffer)));
        ComPtr<ID3D11RenderTargetView> target;
        check("CreateRenderTargetView", device->CreateRenderTargetView(backBuffer.Get(), nullptr, &target));
        const float color[4] = {0.1f, 0.2f, 0.3f, 1};
        context->ClearRenderTargetView(target.Get(), color);
        check("Present (main)", mainSwap->Present(0, 0));
        context->ClearState();
        target.Reset(); backBuffer.Reset(); mainSwap.Reset(); DestroyWindow(window);
        puts("PASS: main-window path; actual Dalamud UI still untested");
        return 0;
    }
    DXGI_SWAP_CHAIN_DESC1 sd = {};
    sd.Width = sd.Height = 16; sd.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    sd.SampleDesc.Count = 1; sd.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    sd.BufferCount = 2; sd.Scaling = DXGI_SCALING_STRETCH;
    sd.SwapEffect = DXGI_SWAP_EFFECT_FLIP_SEQUENTIAL;
    sd.AlphaMode = DXGI_ALPHA_MODE_PREMULTIPLIED;
    ComPtr<IDXGISwapChain1> swap;
    check("CreateSwapChainForComposition", factory->CreateSwapChainForComposition(device.Get(), &sd, nullptr, &swap));
    ComPtr<IDCompositionDevice> composition;
    check("DCompositionCreateDevice", DCompositionCreateDevice(nullptr, IID_PPV_ARGS(&composition)));
    ComPtr<IDCompositionVisual> visual;
    check("CreateVisual", composition->CreateVisual(&visual));
    puts("enter SetContent"); fflush(stdout);
    check("SetContent", visual->SetContent(swap.Get()));
    check("Commit", composition->Commit());
    puts("PASS: composition content accepted; game/UI operation still untested");
    return 0;
}
