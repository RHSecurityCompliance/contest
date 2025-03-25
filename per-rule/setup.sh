#!/bin/bash

set -e

thin_ds_dir=thin_ds
playbooks_dir=playbooks
tests_dir=tests

# strip-off the leading product prefix from all 'thin_ds' datastreams
# to make accessing thme easier/faster for the runner
rhel_major=$(. /etc/os-release && echo ${VERSION_ID%%.*})
ssg_ds_prefix="ssg-rhel${rhel_major}-ds_"
while IFS= read -r -d '' file; do
    if [[ $file =~ ^$ssg_ds_prefix ]]; then
        new_file=${file#$ssg_ds_prefix}
        mv -f "$thin_ds_dir/$file" "$thin_ds_dir/$new_file"
    fi
done < <(find "$thin_ds_dir" -maxdepth 1 -type f -printf '%P\0')

# remove extra metadata from per-rule ansible playbooks to make them
# usable with local ansible-playbook runs
while IFS= read -r -d '' file; do
    sed -i \
        -e '/^[[:space:]]\+hosts:/s/@@HOSTS@@/all/' \
        -e '/^[[:space:]]\+become:/d' \
         "$file"
done < <(find "$playbooks_dir" -maxdepth 1 -type f -print0)

# make all files inside tests dir executable
# (some tests execute other .sh files directly)
chmod +x -R "$tests_dir"

exit 0
