CXX=g++
SRCS=$(wildcard *.cpp)
NAME=vice12_smp

CXXFLAGS=-std=c++17 -O2 -Wall -Wextra -Werror

ifeq ($(OS),Windows_NT)
THREAD_FLAGS=
else
THREAD_FLAGS=-pthread
endif

all:
	$(CXX) $(CXXFLAGS) $(SRCS) -o $(NAME) $(THREAD_FLAGS)
