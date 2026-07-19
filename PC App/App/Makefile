CXX := g++
CXXFLAGS := -std=c++17 -Wall -O2 -Ithird_party
BINDIR := bin

AVAHI_CFLAGS := $(shell pkg-config --cflags avahi-client 2>/dev/null)
AVAHI_LIBS   := $(shell pkg-config --libs avahi-client 2>/dev/null)
CURL_CFLAGS  := $(shell pkg-config --cflags libcurl 2>/dev/null)
CURL_LIBS    := $(shell pkg-config --libs libcurl 2>/dev/null)

.PHONY: all clean

all: $(BINDIR)/network-discovery $(BINDIR)/registration

$(BINDIR):
	mkdir -p $(BINDIR)

$(BINDIR)/network-discovery: network-discovery.cpp | $(BINDIR)
	$(CXX) $(CXXFLAGS) $(AVAHI_CFLAGS) -o $@ $< $(AVAHI_LIBS) -lpthread

$(BINDIR)/registration: registration.cpp | $(BINDIR)
	$(CXX) $(CXXFLAGS) $(CURL_CFLAGS) -o $@ $< $(CURL_LIBS) -lpthread

clean:
	rm -rf $(BINDIR)
