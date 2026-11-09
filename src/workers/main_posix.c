#include <string.h>

#include "worker_entry.h"

int main(int argc, char **argv) {
  if (argc != 4 || strcmp(argv[1], "ir") != 0) {
    return 2;
  }
  return npunlock_ir_worker_main(argc - 1, argv + 1);
}
