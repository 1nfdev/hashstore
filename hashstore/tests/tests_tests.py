
from hs_build_tools.nose import eq_,ok_

def test_docs():
    import doctest
    import hashstore.tests
    r = doctest.testmod(hashstore.tests)
    ok_(r.attempted > 0)
    eq_(r.failed,0)
