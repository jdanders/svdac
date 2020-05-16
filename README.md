# svdac
System Verilog Domain Assignment Checker

Given a set of rules, check verilog files that all assignments meet the rules. Rules are to ensure that "domains" are maintained, for example pipe stage or clock domains.

Rule features:
===============
A rule is an instance of the DACrule dataclass, for example:
`DACrule(left="s2", right=["s1", "r1"], assign="<=", ignore="s2exception")`
Defaults for class:
  * assign = `"<="`
  * ignore = `"noDAC"`

The above rule says that for every non-blocking assignment in the file that has the string "s2" on the left, the variables on the right must have either "s1" or "r1". Exceptions are documented in the code by adding a commented ignore pragma, "s2exception" in this example.

Good according to example rule:
`data_s2 <= data_s1 + calc_r1;`

Bad according to example rule:
`data_s2 <= data_s1 + other_sig;`

Ignored according to example rule:
`data_s2 <= data_s1 + other_sig; //s2exception`

Variable names are strings with `(alphanumeric + '_.[]$:')` characters. All CAPS names are ignored as constants and are not analyzed, as well as literal numbers.

Source code embedded rules:
=============================
These rules can be embedded in the sv, or the default rules will be used:

Default rules:

```
    DACrule('r1', 'r0') through DACrule('r6', 'r5')
    DACrule('s1', 's0') through DACrule('r6', 'r5')
    DACrule('d1', 'd0') through DACrule('r6', 'r5')
    DACrule('r0', 'r0', '=') through DACrule('r5', 'r5', '=')
    DACrule('s0', 's0', '=') through DACrule('s5', 's5', '=')
    DACrule('d0', 'd0', '=') through DACrule('d5', 'd5', '=')
```

Embed format:

`DACrule: <left list> <assignment> <right list> [-- ignore]`

The left and right lists can have number ranges and comma separated sets
The assignment is either `=` or `<=`
The ignore rule is optional, will be set to 'noDAC' if not included

To embed rules, add comments to the sv source file:

```verilog
// DACrule: s0-3, p0-3 = s0-3, p0-3, [0-3] -- OKcomb
// DACrule: s1-3, p1-3 <= s0-2, p0-2, [0-2] -- OKreg
// DACexception: srst, time_cnt_
```

Ranges allow for concise description. First two of the derived rules:

```
DACrule(left='s0', right=['s0', 'p0', '[0]'], assign='=', ignore='OKcomb')
DACrule(left='s1', right=['s1', 'p1', '[1]'], assign='=', ignore='OKcomb')
```


Exceptions embedded in code are specific variables that should be ignored. If any part of an exception is in a line, it will be ignored. In the above example a line with 'i_srst' would be ignored because it has substring 'srst'.

If an ignore comment is added to the code, you can add a ';' to replace the ignored line with a semicolon. This is needed to preserve parsability sometimes.

```verilog
//noDAC    <-- will be replaced with empty space
//noDAC;   <-- will be replaced with ';'
```