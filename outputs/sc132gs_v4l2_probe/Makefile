obj-m += sc132gs.o

KDIR ?= /lib/modules/$(shell uname -r)/build
CXX ?= g++
CXXFLAGS ?= -O2 -std=c++20 -Wall -Wextra -Wpedantic

.PHONY: all module tools clean
all:
	$(MAKE) module tools

module:
	$(MAKE) -C $(KDIR) M=$(CURDIR) modules

tools: sc132gs-sync-check sc132gs-fsync-generator sc132gs-paired-stream sc132gs-ctl

sc132gs-sync-check: sc132gs-sync-check.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

sc132gs-fsync-generator: sc132gs-fsync-generator.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

sc132gs-paired-stream: sc132gs-paired-stream.cpp sc132gs-ae.cpp sc132gs-ae.hpp sc132gs-control-server.cpp sc132gs-control-server.hpp
	$(CXX) $(CXXFLAGS) -pthread -o $@ sc132gs-paired-stream.cpp sc132gs-ae.cpp sc132gs-control-server.cpp

sc132gs-ctl: sc132gs-ctl.cpp sc132gs-mode.cpp sc132gs-mode-linux.cpp sc132gs-mode.hpp
	$(CXX) $(CXXFLAGS) -pthread -o $@ sc132gs-ctl.cpp sc132gs-mode.cpp sc132gs-mode-linux.cpp

clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
	$(RM) sc132gs-sync-check sc132gs-fsync-generator sc132gs-paired-stream sc132gs-ctl
