if [ -z "$TMT_TEST_DATA" ]; then
    echo "TMT_TEST_DATA not set, are you running via tmt?" >&2
    exit 1
fi

[ -z "$_LIB_LIBDIR" ] && _LIB_LIBDIR=$(dirname "${BASH_SOURCE[0]}")

PATH="$_LIB_LIBDIR:$PATH"

. "$_LIB_LIBDIR/at-exit.sh"
. "$_LIB_LIBDIR/backup.sh"
. "$_LIB_LIBDIR/cleanup.sh"
. "$_LIB_LIBDIR/misc.sh"
. "$_LIB_LIBDIR/services.sh"
. "$_LIB_LIBDIR/tmt.sh"

# standardize the following across all bash tests in the suite
{ set -e -x; } 2>/dev/null
