// Times the Odia IndicConformer on random mel features of a given length; prints speed and memory.
#include <onnxruntime_cxx_api.h>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <string>
#include <vector>
static long rss_mb() { FILE* f = fopen("/proc/self/status", "r"); char l[256]; long kb = 0; while (fgets(l, 256, f)) if (!strncmp(l, "VmRSS:", 6)) sscanf(l + 6, "%ld", &kb); fclose(f); return kb / 1024; }
int main(int argc, char** argv) {
  const char* model = argv[1]; int threads = atoi(argv[2]); int secs = atoi(argv[3]);
  Ort::Env env(ORT_LOGGING_LEVEL_WARNING, "t"); Ort::SessionOptions so; so.SetIntraOpNumThreads(threads); so.SetGraphOptimizationLevel(ORT_ENABLE_ALL);
  auto t0 = std::chrono::steady_clock::now();
  Ort::Session s(env, model, so);
  double load = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
  const int64_t T = secs * 100 + 1; std::vector<float> feat(80 * T); std::mt19937 g(1); std::normal_distribution<float> n(0, 1); for (auto& v : feat) v = n(g);
  std::vector<int64_t> shape{1, 80, T}, lshape{1}, len{T};
  Ort::MemoryInfo mi = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
  auto x = Ort::Value::CreateTensor<float>(mi, feat.data(), feat.size(), shape.data(), 3);
  auto l = Ort::Value::CreateTensor<int64_t>(mi, len.data(), 1, lshape.data(), 1);
  const char* in[] = {"audio_signal", "length"}; const char* out[] = {"logprobs"};
  Ort::AllocatorWithDefaultOptions a; auto oname = s.GetOutputNameAllocated(0, a); out[0] = oname.get();
  Ort::Value ins[] = {std::move(x), std::move(l)};
  printf("load %.2fs | rss after load %ld MB\n", load, rss_mb());
  for (int i = 0; i < 4; i++) {
    auto s0 = std::chrono::steady_clock::now(); auto r = s.Run(Ort::RunOptions{nullptr}, in, ins, 2, out, 1);
    double d = std::chrono::duration<double>(std::chrono::steady_clock::now() - s0).count();
    auto sh = r[0].GetTensorTypeAndShapeInfo().GetShape();
    printf("run %d: %.2fs for %ds of audio (RTF %.3f) out [%ld,%ld,%ld] rss %ld MB\n", i, d, secs, d / secs, (long)sh[0], (long)sh[1], (long)sh[2], rss_mb());
  }
}
