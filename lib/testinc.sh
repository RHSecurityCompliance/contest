if [ -z "$TMT_TEST_DATA" ]; then
    echo "TMT_TEST_DATA not set, are you running via tmt?" >&2
    exit 1
fi

[ -z "$_LIBDIR" ] && _LIBDIR=$(dirname "${BASH_SOURCE[0]}")

PATH="$_LIBDIR:$PATH"

. "$_LIBDIR/at-exit.sh"
. "$_LIBDIR/backup.sh"
. "$_LIBDIR/cleanup.sh"
. "$_LIBDIR/misc.sh"
. "$_LIBDIR/services.sh"
. "$_LIBDIR/tmt.sh"

# standardize the following across all bash tests in the suite
{ set -e -x; } 2>/dev/null
