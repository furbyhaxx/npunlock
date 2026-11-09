#ifndef NPUNLOCK_SESSION_PLATFORM_H
#define NPUNLOCK_SESSION_PLATFORM_H

#include <stdbool.h>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

typedef CRITICAL_SECTION session_mutex;
typedef LONG session_refcount;
typedef HMODULE session_library;

static inline bool session_mutex_init(session_mutex *lock) {
  InitializeCriticalSection(lock);
  return true;
}
static inline void session_mutex_destroy(session_mutex *lock) { DeleteCriticalSection(lock); }
static inline void session_mutex_lock(session_mutex *lock) { EnterCriticalSection(lock); }
static inline void session_mutex_unlock(session_mutex *lock) { LeaveCriticalSection(lock); }
static inline void session_reference_init(session_refcount *count) { *count = 1; }
static inline void session_reference_retain(session_refcount *count) {
  InterlockedIncrement(count);
}
static inline long session_reference_release(session_refcount *count) {
  return InterlockedDecrement(count);
}
static inline session_library session_library_open(void) {
  return LoadLibraryExW(L"ze_loader.dll", NULL, LOAD_LIBRARY_SEARCH_SYSTEM32);
}
static inline void session_library_close(session_library library) { FreeLibrary(library); }
#else
#include <dlfcn.h>
#include <pthread.h>
#include <stdatomic.h>

typedef pthread_mutex_t session_mutex;
typedef atomic_uint session_refcount;
typedef void *session_library;

static inline bool session_mutex_init(session_mutex *lock) {
  return pthread_mutex_init(lock, NULL) == 0;
}
static inline void session_mutex_destroy(session_mutex *lock) { pthread_mutex_destroy(lock); }
static inline void session_mutex_lock(session_mutex *lock) { pthread_mutex_lock(lock); }
static inline void session_mutex_unlock(session_mutex *lock) { pthread_mutex_unlock(lock); }
static inline void session_reference_init(session_refcount *count) { atomic_init(count, 1); }
static inline void session_reference_retain(session_refcount *count) {
  atomic_fetch_add_explicit(count, 1, memory_order_relaxed);
}
static inline unsigned session_reference_release(session_refcount *count) {
  return atomic_fetch_sub_explicit(count, 1, memory_order_acq_rel) - 1;
}
static inline session_library session_library_open(void) {
  return dlopen("libze_loader.so.1", RTLD_NOW | RTLD_LOCAL);
}
static inline void session_library_close(session_library library) { dlclose(library); }
#endif
#endif
