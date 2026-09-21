// registration - subnet scanner: queries every host on this machine's /24 for
// :5000/robots (RIFT's fleet registry, or NORA's) and lists the robots found.
// Builds on Windows and Linux with no curl or nlohmann; the same code backs the
// hub's own --scan flag (see rift_scan.h).

#include "rift_scan.h"
#include "rift_util.h"

int main() {
    rift::runScan(rift::localIp(), 5000);
    return 0;
}
