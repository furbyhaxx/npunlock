#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "npunlock/error.h"

#include "worker_process.h"

#ifndef NPUNLOCK_POSIX_WORKER_FIXTURE
#error "NPUNLOCK_POSIX_WORKER_FIXTURE must name the worker fixture executable"
#endif

static npunlock_view fixture_path(void) {
  static const char path[] = NPUNLOCK_POSIX_WORKER_FIXTURE;
  return (npunlock_view){(const uint8_t *)path, sizeof(path) - 1};
}

static int buffer_equals(const npunlock_buffer *buffer, const char *expected) {
  size_t size = strlen(expected);
  return buffer->size == size && memcmp(buffer->data, expected, size) == 0;
}

static int test_echo(const char *mode) {
  static const uint8_t request[] = "worker request";
  npunlock_worker_process_result result = {0};
  npunlock_status status = npunlock_worker_process_run(
      fixture_path(), mode, (npunlock_view){request, sizeof(request) - 1}, 1024, 2000, &result);
  int passed = status == NPUNLOCK_STATUS_OK && result.process_exit_code == 0 &&
               result.response.size == sizeof(request) - 1 &&
               memcmp(result.response.data, request, sizeof(request) - 1) == 0 &&
               buffer_equals(&result.stdout_log, "fixture stdout\n") &&
               buffer_equals(&result.stderr_log, "fixture stderr\n");
  if (!passed) {
    fprintf(stderr, "POSIX worker echo failed: %s exit=%u response=%zu stdout=%zu stderr=%zu\n",
            npunlock_status_name(status), result.process_exit_code, result.response.size,
            result.stdout_log.size, result.stderr_log.size);
  }
  npunlock_worker_process_result_release(&result);
  return passed;
}

static int test_timeout(void) {
  static const uint8_t request[] = "timeout request";
  npunlock_worker_process_result result = {0};
  npunlock_status status = npunlock_worker_process_run(
      fixture_path(), "hang", (npunlock_view){request, sizeof(request) - 1}, 1024, 100, &result);
  int passed = status == NPUNLOCK_STATUS_TIMEOUT && result.process_exit_code != 0;
  if (!passed) {
    fprintf(stderr, "POSIX worker timeout failed: %s exit=%u\n", npunlock_status_name(status),
            result.process_exit_code);
  }
  npunlock_worker_process_result_release(&result);
  return passed;
}

static int test_wine(void) {
  static const char payload[] = NPUNLOCK_WINE_FIXTURE_DIR "/payload with spaces.exe";
  static const char prefix[] = NPUNLOCK_WINE_FIXTURE_DIR "/prefix with spaces";
  static const uint8_t request[] = {0, 1, 0xff, 0x80, 4, 0};
  char *path = getenv("PATH") == NULL ? NULL : strdup(getenv("PATH"));
  char *old_prefix = getenv("WINEPREFIX") == NULL ? NULL : strdup(getenv("WINEPREFIX"));
  npunlock_worker_process_result result = {0};
  int passed =
      setenv("PATH", NPUNLOCK_WINE_FIXTURE_DIR, 1) == 0 && setenv("WINEPREFIX", prefix, 1) == 0;
  npunlock_status status = npunlock_worker_process_run(
      (npunlock_view){(const uint8_t *)payload, sizeof(payload) - 1}, "movi",
      (npunlock_view){request, sizeof(request)}, 1024, 2000, &result);
  passed = passed && status == NPUNLOCK_STATUS_OK && result.process_exit_code == 0 &&
           result.response.size == sizeof(request) &&
           memcmp(result.response.data, request, sizeof(request)) == 0 &&
           result.stdout_log.size == 0 &&
           buffer_equals(&result.stderr_log, "wine fixture stderr\n");
  npunlock_worker_process_result_release(&result);
  setenv("PATH", "", 1);
  status = npunlock_worker_process_run(
      (npunlock_view){(const uint8_t *)payload, sizeof(payload) - 1}, "movi",
      (npunlock_view){request, sizeof(request)}, 1024, 2000, &result);
  passed = passed && status == NPUNLOCK_STATUS_NOT_FOUND;
  npunlock_worker_process_result_release(&result);
  if (path == NULL)
    unsetenv("PATH");
  else
    setenv("PATH", path, 1);
  if (old_prefix == NULL)
    unsetenv("WINEPREFIX");
  else
    setenv("WINEPREFIX", old_prefix, 1);
  free(path);
  free(old_prefix);
  if (!passed)
    fprintf(stderr, "Wine worker launcher contract failed\n");
  return passed;
}

int main(int argc, char **argv) {
  if (argc == 2 && strcmp(argv[1], "wine") == 0)
    return test_wine() ? 0 : 1;
  return test_echo("echo") && test_echo("late-close") && test_timeout() ? 0 : 1;
}
