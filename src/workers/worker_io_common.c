#include "worker_io.h"

bool npunlock_worker_checked_add(size_t left, size_t right, size_t *result) {
  if (left > SIZE_MAX - right) {
    return false;
  }
  *result = left + right;
  return true;
}

bool npunlock_worker_checked_mul(size_t left, size_t right, size_t *result) {
  if (left != 0 && right > SIZE_MAX / left) {
    return false;
  }
  *result = left * right;
  return true;
}
