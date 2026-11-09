#include <stdint.h>
#include <stdio.h>

#include "ir_protocol.h"
#include "worker_process.h"
#include "worker_protocol.h"

#ifndef NPUNLOCK_POSIX_IR_WORKER
#error "NPUNLOCK_POSIX_IR_WORKER must name the IR worker executable"
#endif

static int rejects_request(const uint8_t *data, size_t size) {
  static const char path[] = NPUNLOCK_POSIX_IR_WORKER;
  npunlock_worker_process_result result = {0};
  npunlock_status status =
      npunlock_worker_process_run((npunlock_view){(const uint8_t *)path, sizeof(path) - 1}, "ir",
                                  (npunlock_view){data, size}, 1024, 2000, &result);
  int passed =
      status == NPUNLOCK_STATUS_OK && result.process_exit_code == 0 &&
      result.response.size >= NPUNLOCK_IR_RESPONSE_HEADER_SIZE &&
      npunlock_worker_load_u32(result.response.data) == NPUNLOCK_IR_RESPONSE_MAGIC &&
      npunlock_worker_load_u32(result.response.data + 4) == NPUNLOCK_IR_PROTOCOL_VERSION &&
      npunlock_worker_load_u32(result.response.data + 8) == NPUNLOCK_IR_WORKER_BAD_REQUEST &&
      npunlock_worker_load_u64(result.response.data + 72) == 0 &&
      npunlock_worker_load_u64(result.response.data + 80) ==
          result.response.size - NPUNLOCK_IR_RESPONSE_HEADER_SIZE;
  if (!passed) {
    fprintf(stderr, "IR worker rejection failed: %s exit=%u response=%zu\n",
            npunlock_status_name(status), result.process_exit_code, result.response.size);
  }
  npunlock_worker_process_result_release(&result);
  return passed;
}

int main(void) {
  uint8_t request[NPUNLOCK_IR_REQUEST_HEADER_SIZE + 1] = {0};
  if (!rejects_request(request, 1)) {
    return 1;
  }
  npunlock_worker_store_u32(request, NPUNLOCK_IR_REQUEST_MAGIC);
  npunlock_worker_store_u32(request + 4, NPUNLOCK_IR_PROTOCOL_VERSION);
  npunlock_worker_store_u32(request + 36, NPUNLOCK_IR_WORKER_QUERY);
  npunlock_worker_store_u64(request + 16, 1);
  if (!rejects_request(request, sizeof(request))) {
    return 1;
  }
  npunlock_worker_store_u32(request + 36, NPUNLOCK_IR_WORKER_COMPILE);
  npunlock_worker_store_u64(request + 16, UINT64_MAX);
  return rejects_request(request, sizeof(request)) ? 0 : 1;
}
