
TODO:

- `CONTEST_QUIET`
   - have tmt.report() func silently discard 'pass' results for any 'name'
     that isn't None (eg. still report 'pass' for / , the test itself)
    - this is needed to detect waived-but-passed, even if we discard
      the pass afterwards
   - if this var is set, then don't discard 'pass'


- move all python stuff to `lib/python/` and leave `lib/` for other things too
  - runconf
  - waiveconf
  - pseudotty and other executables
  ...
  - adjust `libdir` in `util` appropriately ?
