"""Parameter types from Itanium-mangled names (the subset the script modules import).

    parse(name) -> (path, params, is_const_member) or None when the name uses something not handled here
        path    list of name components, e.g. ['app', 'lua_bind', 'AttackModule__enable_safe_pos_impl']
        params  list of type descriptors:
                  'i' 'j' 'l' 'm' 'b' 'c' 'h' 's' 't' 'x' 'y' 'f' 'd'      built-in
                  ('ptr', T) ('ref', T) ('const', T) ('class', 'a::b::C')
"""
import re

BUILTIN = set('ijlmbchstxyfdvaw')


class _P:
    def __init__(self, s):
        self.s = s
        self.i = 0
        self.subs = []

    def peek(self, n=1):
        return self.s[self.i:self.i + n]

    def number(self):
        j = self.i
        while self.s[j].isdigit():
            j += 1
        v = int(self.s[self.i:j])
        self.i = j
        return v

    def source_name(self):
        n = self.number()
        v = self.s[self.i:self.i + n]
        self.i += n
        return v

    def subst(self):
        # S_ , S<base36>_
        self.i += 1
        j = self.s.index('_', self.i)
        code = self.s[self.i:j]
        self.i = j + 1
        idx = 0 if code == '' else int(code, 36) + 1
        return self.subs[idx]

    def nested(self, is_function):
        """N [K] prefix+ E ; returns (components, const)"""
        self.i += 1
        const = False
        if self.peek() == 'K':
            const = True
            self.i += 1
        comps = []
        while self.peek() != 'E':
            c = self.peek()
            if c == 'S' and self.peek(2) != 'St':
                t = self.subst()
                if t[0] != 'class':
                    raise ValueError('substitution of a non-class in a nested name')
                comps = t[1].split('::')
                continue
            if c.isdigit():
                comps.append(self.source_name())
            elif self.peek(2) in ('C1', 'C2', 'D0', 'D1', 'D2'):
                comps.append(('~' if self.peek() == 'D' else '') + comps[-1])
                self.i += 2
            elif self.peek(2) == 'cv':
                self.i += 2
                t = self.type()
                comps.append('operator ' + str(t))
            elif c.islower():
                comps.append('operator_' + self.peek(2))
                self.i += 2
            else:
                raise ValueError('nested name: ' + self.s[self.i:])
            if self.peek() == 'I':
                raise ValueError('template')
            if self.peek() != 'E' or not is_function:
                self.subs.append(('class', '::'.join(comps)))
        self.i += 1
        return comps, const

    def type(self):
        c = self.peek()
        if c in 'PRKO':
            self.i += 1
            inner = self.type()
            t = ({'P': 'ptr', 'R': 'ref', 'K': 'const', 'O': 'ref'}[c], inner)
            self.subs.append(t)
            return t
        if c == 'N':
            comps, _ = self.nested(False)
            return ('class', '::'.join(comps))
        if c == 'S':
            if self.peek(2) == 'St':
                raise ValueError('std')
            return self.subst()
        if c.isdigit():
            t = ('class', self.source_name())
            self.subs.append(t)
            return t
        if c in BUILTIN:
            self.i += 1
            return c
        raise ValueError('type: ' + self.s[self.i:])


def parse(name):
    if not name.startswith('_Z'):
        return None
    p = _P(name)
    p.i = 2
    try:
        if p.peek() == 'N':
            path, const = p.nested(True)
        elif p.peek().isdigit():
            path, const = [p.source_name()], False
        else:
            return None
        params = []
        while p.i < len(name):
            params.append(p.type())
        if params == ['v']:
            params = []
        return path, params, const
    except (ValueError, IndexError):
        return None


def is_member(path):
    """non-static member function (takes `this` in x0)? The script classes and the L2C value/agent classes."""
    if is_static_value(path):
        return False
    return len(path) >= 3 and (path[0] == 'lua2cpp' or (path[0] == 'lib' and path[1] in ('L2CAgent', 'L2CValue', 'L2CTable')))


def gvalue_name(sym):
    """S20: 'math_pi' for the DATA symbol lib::L2CAgent::math_pi (a constant L2CValue of main), else None. Exactly
    _ZN3lib8L2CAgent<n><name>E with nothing after: a function (math_abs(const L2CValue &)) has its parameters there."""
    m = re.fullmatch(r'_ZN3lib8L2CAgent(\d+)(\w+)E', sym)
    if not m or len(m.group(2)) != int(m.group(1)) or not m.group(2).startswith('math_'):
        return None
    return m.group(2)


def is_static_value(path):
    """S3: static functions of the script classes that return an L2CValue through x8 and take NO `this`: at every
    call site in lua2cpp_common x0 is the first L2CValue argument (lib::L2CAgent::math_abs(const L2CValue &) ...)."""
    path = list(path)
    if path[0] == 'app' and len(path) == 3 and path[2] == 'new_l2c_table':
        return True                                      # S20: app::LinkEvent::new_l2c_table() etc.: a fresh table through x8
    return (path[:2] == ['lib', 'L2CAgent'] and len(path) == 3 and path[2].startswith('math_'))   # S9: lerp is NOT here: it is a member (x0 = this, unused; a, b, t in x1..x3)


def strip(t):
    while isinstance(t, tuple) and t[0] == 'const':
        t = t[1]
    return t


def reg_class(t):
    """'x' integer register, 'f' float register, 'lv' L2CValue by value (pointer to a copy in an integer register)"""
    t = strip(t)
    if t in ('f', 'd'):
        return 'f'
    if isinstance(t, tuple) and t[0] == 'class':
        if t[1] == 'lib::L2CValue':
            return 'lv'
        if t[1].startswith('phx::Vector') or t[1].startswith('lib::'):
            return '?'
        return 'x'                    # phx::Hash40 (8 bytes) and the app:: enum classes
    return 'x'


if __name__ == '__main__':
    import sys
    for n in sys.argv[1:]:
        print(parse(n))
