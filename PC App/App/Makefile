CXX ?= g++
CXXFLAGS := -std=c++17 -Wall -O2 -Ithird_party
BINDIR := bin

# No Avahi/curl/nlohmann needed: mDNS and HTTP are built in (see rift_hub.h), so
# the same sources build on Linux and on Windows (MinGW-w64).
ifeq ($(OS),Windows_NT)
    EXE := .exe
    LDFLAGS := -static
    LDLIBS := -lws2_32 -liphlpapi -lpthread
else
    EXE :=
    LDFLAGS :=
    LDLIBS := -lpthread
endif

HEADERS := rift_util.h rift_hub.h rift_scan.h third_party/httplib.h third_party/minijson.hpp

.PHONY: all clean

all: $(BINDIR)/network-discovery$(EXE) $(BINDIR)/registration$(EXE)

$(BINDIR):
	mkdir -p $(BINDIR)

$(BINDIR)/network-discovery$(EXE): network-discovery.cpp $(HEADERS) | $(BINDIR)
	$(CXX) $(CXXFLAGS) $(LDFLAGS) -o $@ $< $(LDLIBS)

$(BINDIR)/registration$(EXE): registration.cpp $(HEADERS) | $(BINDIR)
	$(CXX) $(CXXFLAGS) $(LDFLAGS) -o $@ $< $(LDLIBS)

clean:
	rm -rf $(BINDIR)
