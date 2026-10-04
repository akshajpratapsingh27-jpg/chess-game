SRCS=$(wildcard *.c)
NAME=vice12_smp

ifeq ($(OS),Windows_NT)
THREAD_FLAGS=
else
THREAD_FLAGS=-pthread
endif

all:
	gcc $(SRCS) -o $(NAME) $(THREAD_FLAGS) -O2 -Wall -Wextra