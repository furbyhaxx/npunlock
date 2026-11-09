#ifndef NPUNLOCK_WORKERS_WORKER_IO_H
#define NPUNLOCK_WORKERS_WORKER_IO_H

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
typedef HANDLE npunlock_worker_handle;
#else
typedef int npunlock_worker_handle;
#endif

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

bool npunlock_worker_checked_add(size_t left, size_t right, size_t *result);
bool npunlock_worker_checked_mul(size_t left, size_t right, size_t *result);
bool npunlock_worker_read_all(npunlock_worker_handle handle, size_t maximum, uint8_t **data,
                              size_t *size);
bool npunlock_worker_write_all(npunlock_worker_handle handle, const uint8_t *data, size_t size);
bool npunlock_worker_response_handle(int argc, char **argv, npunlock_worker_handle *response);

#endif
