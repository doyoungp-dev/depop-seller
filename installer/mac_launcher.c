/* The macOS app's main program: Depop Seller.app/Contents/MacOS/depop-seller.
 *
 * All it does is hand over to depop-seller.sh next to it, which holds the real launcher. It exists
 * because macOS looks at an app's main program to decide how to run it: a script has no Apple
 * silicon code in it, so an Apple silicon Mac without Rosetta answers a double-click with
 * "To open Depop Seller, you need to install Rosetta" and never runs the script at all. A small
 * universal binary (Apple silicon + Intel) runs natively everywhere.
 *
 * Rebuild it on a Mac after changing this file (clang signs it ad hoc, which Apple silicon needs):
 *   clang -Os -arch arm64 -arch x86_64 -mmacosx-version-min=11.0 \
 *         -o "Depop Seller.app/Contents/MacOS/depop-seller" installer/mac_launcher.c
 *   strip "Depop Seller.app/Contents/MacOS/depop-seller"
 */

#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

int main(void) {
    char folder[PATH_MAX], script[PATH_MAX];
    uint32_t size = sizeof folder;
    if (_NSGetExecutablePath(folder, &size) != 0)
        return 1;
    char *slash = strrchr(folder, '/');
    if (slash == NULL)
        return 1;
    *slash = '\0';
    if (snprintf(script, sizeof script, "%s/depop-seller.sh", folder) >= (int)sizeof script)
        return 1;
    /* exec, not spawn: the script becomes this process, so macOS sees the app running until the
       script ends, and Quit in the Dock reaches the script's trap. */
    char *args[] = {"/bin/bash", script, NULL};
    execv("/bin/bash", args);
    return 127;
}
