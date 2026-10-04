// misc.c
#include "stdio.h"

#if defined(_WIN32) || defined(WIN32)
#include "windows.h"
#else
#include "sys/time.h"
#endif

int GetTimeMs() {
#if defined(_WIN32) || defined(WIN32)
  return GetTickCount();
#else
  struct timeval t;
  gettimeofday(&t, NULL);
  return t.tv_sec*1000 + t.tv_usec/1000;
#endif
}

