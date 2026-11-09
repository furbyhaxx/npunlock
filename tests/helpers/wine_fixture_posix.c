#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
  const char *prefix = getenv("WINEPREFIX");
  if (argc != 4 || strcmp(argv[2], "movi") != 0 || strcmp(argv[3], "--response-stdout") != 0 ||
      prefix == NULL || prefix[0] != '/' || strstr(argv[1], "payload with spaces.exe") == NULL) {
    return 2;
  }
  unsigned char buffer[4096];
  for (;;) {
    ssize_t count = read(STDIN_FILENO, buffer, sizeof(buffer));
    if (count < 0 && errno == EINTR)
      continue;
    if (count < 0)
      return 3;
    if (count == 0)
      break;
    size_t offset = 0;
    while (offset < (size_t)count) {
      ssize_t written = write(STDOUT_FILENO, buffer + offset, (size_t)count - offset);
      if (written < 0 && errno == EINTR)
        continue;
      if (written <= 0)
        return 4;
      offset += (size_t)written;
    }
  }
  fputs("wine fixture stderr\n", stderr);
  return 0;
}
