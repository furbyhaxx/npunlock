#include "worker_io.h"

#include <errno.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

bool npunlock_worker_write_all(npunlock_worker_handle handle, const uint8_t *data, size_t size) {
  while (size != 0) {
    size_t chunk = size > 16384 ? 16384 : size;
    ssize_t written = write(handle, data, chunk);
    if (written < 0 && errno == EINTR) {
      continue;
    }
    if (written <= 0) {
      return false;
    }
    data += written;
    size -= (size_t)written;
  }
  return true;
}

bool npunlock_worker_read_all(npunlock_worker_handle handle, size_t maximum, uint8_t **data,
                              size_t *size) {
  uint8_t *buffer = NULL;
  size_t used = 0;
  size_t capacity = 0;
  for (;;) {
    uint8_t chunk[16384];
    ssize_t received = read(handle, chunk, sizeof(chunk));
    if (received < 0 && errno == EINTR) {
      continue;
    }
    if (received < 0 || (received > 0 && (size_t)received > maximum - used)) {
      free(buffer);
      return false;
    }
    if (received == 0) {
      *data = buffer;
      *size = used;
      return true;
    }
    if (used + (size_t)received > capacity) {
      size_t next = capacity == 0 ? sizeof(chunk) : capacity;
      uint8_t *replacement;
      while (next < used + (size_t)received) {
        next = next > maximum / 2 ? maximum : next * 2;
      }
      if (next > maximum) {
        next = maximum;
      }
      replacement = realloc(buffer, next);
      if (replacement == NULL) {
        free(buffer);
        return false;
      }
      buffer = replacement;
      capacity = next;
    }
    memcpy(buffer + used, chunk, (size_t)received);
    used += (size_t)received;
  }
}

bool npunlock_worker_response_handle(int argc, char **argv, npunlock_worker_handle *response) {
  char *end = NULL;
  long descriptor;
  if (response == NULL || argc != 3 || strcmp(argv[1], "--response-fd") != 0) {
    return false;
  }
  errno = 0;
  descriptor = strtol(argv[2], &end, 10);
  if (errno != 0 || end == argv[2] || *end != '\0' || descriptor < 3 || descriptor > INT_MAX) {
    return false;
  }
  *response = (int)descriptor;
  return true;
}
