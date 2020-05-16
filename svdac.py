#! /usr/bin/env python3
"""System Verilog Domain Assignment Checker

Given a set of rules, check verilog files that all assignments meet the
rules. Rules are to ensure that "domains" are maintained, for example pipe
stage or clock domains.

A rule is an instance of the DACrule dataclass, for example:
DACrule(left="s2", right=["s1", "r1"], assign="<=", ignore="s2exception")
  defaults for class: assign = "<=", ignore="noDAC"

The above rule says that for every non-blocking assignment in the file
that has the string "s2" on the left, the variables on the right must
have either "s1" or "r1". Exceptions are documented in the code by
adding a commented ignore pragma, "s2exception" in this example.

Good according to example rule:
data_s2 <= data_s1 + calc_r1;

Bad according to example rule:
data_s2 <= data_s1 + other_sig;

Ignored according to example rule:
data_s2 <= data_s1 + other_sig; //s2exception

Variable names are strings with (alphanumeric + '_.[]$:')
characters. All CAPS names are ignored as constants and are not
analyzed, as well as literal numbers.

Source code embedded rules:
=============================
These rules can be embedded in the sv, or the default rules will be used:
    DACrule('r1', 'r0') through DACrule('r6', 'r5')
    DACrule('s1', 's0') through DACrule('r6', 'r5')
    DACrule('d1', 'd0') through DACrule('r6', 'r5')
    DACrule('r0', 'r0', '=') through DACrule('r5', 'r5', '=')
    DACrule('s0', 's0', '=') through DACrule('s5', 's5', '=')
    DACrule('d0', 'd0', '=') through DACrule('d5', 'd5', '=')

Embed format: DACrule: <left list> <assignment> <right list> [-- ignore]
The left and right lists can have number ranges and comma separated sets
The assignment is either '=' or '<='
The ignore rule is optional, will be set to 'noDAC' if not included

To embed rules, add comments to the sv source file:
// DACrule: s0-3, p0-3 = s0-3, p0-3, [0-3] -- OKcomb
// DACrule: s1-3, p1-3 <= s0-2, p0-2, [0-2] -- OKreg
// DACexception: srst, time_cnt_

Ranges allow for concise description. First two of the derived rules:
DACrule(left='s0', right=['s0', 'p0', '[0]'], assign='=', ignore='OKcomb')
DACrule(left='s1', right=['s1', 'p1', '[1]'], assign='=', ignore='OKcomb')

Exceptions embedded in code are specific variables that should be
ignored. If any part of an exception is in a line, it will be
ignored. In the above example a line with 'i_srst' would be ignored
because it has substring 'srst'.

If an ignore comment is added to the code, you can add a ';' to
replace the ignored line with a semicolon. This is needed to preserve
parsability sometimes.
//noDAC    <-- will be replaced with empty space
//noDAC;   <-- will be replaced with ';'
"""
import os
import re
import sys
import argparse
from dataclasses import dataclass
import simple_verilog_parser

assert sys.version_info > (3, 7), "Requires python 3.7+ for dataclass"


@dataclass
class DACrule:
    '''Documents a SV rule to be checked.

    left: string to match on left hand of assignment
    right: string to match on right hand of assignment
    assign: string to match as the assignment operator, '=' or '<=' typically
    ignore: if this string exists on the line, ignore violations of the rule
    exclude: set internally to avoid collisions when subset names occur
    '''
    left: str
    right: list
    assign: str = "<="
    ignore: str = "noDAC"
    exclude: list = None

    def __eq__(self, other):
        return (self.left == other.left) and (self.assign == other.assign)

    def __str__(self):
        return f"{self.left} {self.assign} {self.right}"


exceptions = []
default_rules = []
for letter in ['r', 's', 'd']:
    for number in range(6):
        default_rules.append(DACrule(f'{letter}{number+1}',
                                     [f'{letter}{number}'],
                                     assign='<='))
        default_rules.append(DACrule(f'{letter}{number}',
                                     [f'{letter}{number}'],
                                     assign='='))

# Regex for embedded rule extraction
embed_rule_re = re.compile(r'DACrule: (.*)')
embed_exception_re = re.compile(r'DACexception: (.*)')

# Regex to identify and parse code pieces
variable_re = re.compile(r'[\w.\[\]$:]+')
hasalpha_re = re.compile(r'[a-zA-Z]+')
arr_re = re.compile(r'\[.*?\]')
raw_range_re = re.compile(r'\d+-\d+')

# Global variable set by parameter
VERBOSE = False

# Pretty colors
if 'TERM' in os.environ and 'color' in os.environ['TERM']:
    RED = '\033[91m'
    YEL = '\033[93m'
    UYEL = '\033[93m'+'\033[4m'
    ENDC = '\033[0m'
else:
    RED = ''
    YEL = ''
    UYEL = ''
    ENDC = ''


def is_word_in(word, line):
    ''' Identify if whole word (not part of other word) is in line
    Also, treat '_' as space for matching '''
    word = word.replace(' ', '\t').replace('_', ' ')
    line = line.replace(' ', '\t').replace('_', ' ')
    return True if re.search(rf"\b({word})\b", line) else False


def check_excluded_match(rule, lh_line):
    ''' Determine if the rule excludes the lh_line '''
    if rule.exclude:
        # Excluded strings are to avoid subsets: s0 shouldn't match s0_c
        for exc in rule.exclude:
            if is_word_in(exc, lh_line):
                return True


def fix_arrays(line):
    ''' Extra spaces in verilog arrays makes parsing hard, so remove '''
    linenum = line.linenum
    arrs = arr_re.findall(line)
    if arrs:
        for arr in arrs:
            line = line.replace(arr, arr.replace(" ", ""))
    return simple_verilog_parser.StrLine(line, linenum)


def process_line(line, rule, args):
    ''' Examine the line of code against the provided rule '''
    violations = 0
    passes = 0
    # Some hacky cleanup
    line = fix_arrays(line)
    # Only compare against actual line of code, not any 'case' or 'if' deps
    base_line = line.split(simple_verilog_parser.if_del)[0]\
                    .split(simple_verilog_parser.case_del)[0]
    if "=" in base_line:
        # Only compare up to the first '='
        base_line = base_line[:base_line.index('=')+2]

    # Add spaces around assign to be sure match is accurate
    full_assign = f" {rule.assign} "
    # Check if the assignment matching this rule is in this line
    if full_assign in base_line:
        (lh_line, rh_line) = line.split(full_assign, 1)

        # Excluded strings are to avoid subsets: s0 shouldn't match s0_c
        if check_excluded_match(rule, lh_line):
            return violations, passes

        # Check that the left hand side matches the rule
        if is_word_in(rule.left, lh_line):

            # Extract all the right hand variables
            r_variables = variable_re.findall(rh_line)
            if len(r_variables) == 0:
                if VERBOSE:
                    print(f"Right hand side has no variable:\n  {line}")
                return violations, passes

            # Check that each right hand variable matches the rule
            for variable in r_variables:
                # Check all exceptions to the rule
                if variable.isupper():
                    if VERBOSE:
                        print(f"Ignored all-caps variable {variable}")
                    continue
                # Handle 1'b0 type literal
                literals = [variable.strip(ii).isdigit()
                            for ii in ['h', 'd', 'b', 'o']]
                if variable.isdigit() or any(literals):
                    if VERBOSE:
                        print(f"Ignored numerical variable {variable}")
                    continue
                if not hasalpha_re.search(variable):
                    continue
                if (variable == simple_verilog_parser.if_del
                        or variable == simple_verilog_parser.case_del):
                    continue
                excepted = [exc for exc in exceptions if exc in line]
                if any(excepted):
                    continue

                # There are no exceptions for this variable, check rule
                missing = 0
                for right_rule in rule.right:
                    missing += (not is_word_in(right_rule, variable))
                if missing == len(rule.right):
                    violations += 1
                    print(f"{RED}Rule {rule} "
                          f"violation ({YEL}{variable}{RED}):{ENDC}\n"
                          f"\t(near line {line.linenum})\n"
                          f"\t{line.replace(variable,UYEL+variable+ENDC)}")
                    if args.one:
                        sys.exit(1)
                else:
                    passes += 1

    return violations, passes


def extract_raw_range(raw):
    ''' Given raw string of embedded rules like 's0-1, p0-1', extrapolate
    each instance, like [s0, s1, p0, p1]. Return the array and stride size '''
    result = []
    for subraw in raw.split(","):
        # Each sub element can have its own range, like s0-3
        rawrange = raw_range_re.findall(subraw)
        if rawrange:
            bottom = int(rawrange[0].split("-")[0])
            top = int(rawrange[0].split("-")[1])
            stride = top - bottom + 1
            for ii in range(bottom, top+1):
                result.append(raw_range_re.sub(str(ii), subraw.strip()))
        else:
            # No range, just use it directly
            result.append(subraw.strip())
            stride = 1
    return result, stride


def process_raw_rules(raw_rules):
    ''' Translate raw embedded rules to DACrule instances:
    'n3_c = s3, p3, e3, n3_c, [3] -- OKcomb'
    becomes
    DACrule(left='n3_c', right=['s3', 'p3', 'e3', 'n3_c', '[3]'],
            assign='=', ignore='OKcomb', exclude=None)
    '''
    if len(raw_rules) == 0:
        return default_rules
    rules = []

    for raw in raw_rules:
        # raw example: s0-3, p0-3, e0-3 = s0-3, p0-3, e0-3, [0-3] -- OKcomb
        if "<=" in raw:
            assign = "<="
        else:
            assign = "="
        lh, rem = raw.split(assign)
        if '--' in rem:
            rh, ignore = rem.split('--')
            ignore = ignore.strip()
        else:
            # No ignore option, use default
            rh = rem
            ignore = default_rules[0].ignore

        left_arr, lhstride = extract_raw_range(lh)
        right_arr, rhstride = extract_raw_range(rh)

        if lhstride != rhstride:
            # In order to generate ranges, the strides must match
            print("Embedded rules do not have matching number ranges")
            sys.exit(-2)

        for ii in range(len(left_arr)):
            new_rule = DACrule(left_arr[ii],
                               right_arr[ii % lhstride::rhstride],
                               assign, ignore)
            # Override with later rules if existing already
            if new_rule in rules:
                rules = [new_rule if ii == new_rule else ii for ii in rules]
            else:
                rules.append(new_rule)

    # If there are subsets on left-hand strings, false matches will occur
    for rule in rules:
        for other in rules:
            if (rule.left in other.left
                and not (rule.left == other.left)
                    and (rule.assign == other.assign)):
                # This is a subset, and will match unless excluded
                if rule.exclude:
                    rule.exclude.append(other.left)
                else:
                    rule.exclude = [other.left]
    return rules


def remove_ignored_lines(file_contents, rule):
    ''' Replace lines marked with rule.ignore with blank lines '''
    lines = file_contents.splitlines()
    result = []
    for line in lines:
        if rule.ignore in line:
            # Add \n to preserve line number count
            result.append("\n")
        else:
            result.append(line)
        # Special rule for ignoring variables but keep end of line ;
        if f"{rule.ignore};" in line:
            result.append(';')
    return "\n".join(result)


def create_arg_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'sv_file', nargs='+', help='list of files to process')
    parser.add_argument(
        '-1', '--one', action='store_true', help='quit on first error')
    parser.add_argument(
        '-v', '--verbose', action='store_true', help='print verbose info')
    parser.add_argument(
        '-r', '--rules', action='store_true', help='print rules')
    return parser


def main(args):
    parser = create_arg_parser()
    args = parser.parse_args(args[1:])
    errors = 0
    passes = 0
    if args.verbose:
        global VERBOSE
        VERBOSE = True
        simple_verilog_parser.VERBOSE = True

    for filepath in args.sv_file:
        with open(filepath) as fh:
            file_contents = fh.read()

        # Extract rules from sv
        raw_rules = embed_rule_re.findall(file_contents)
        rules = process_raw_rules(raw_rules)
        for rule in rules:
            if args.rules:
                print(repr(rule))
            file_contents = remove_ignored_lines(file_contents, rule)

        # Extract exceptions from sv
        raw_exceptions = embed_exception_re.findall(file_contents)
        if raw_exceptions:
            raw = ",".join(raw_exceptions)
            global exceptions
            exceptions = [exc.strip() for exc in raw.split(",") if exc]

        lines = simple_verilog_parser.file_to_lines(file_contents)

        for line in lines:
            for rule in rules:
                erred, passed = process_line(line, rule, args)
                errors += erred
                passes += passed

    print(f"Correct checks: {passes}, Rule violations: {errors}")
    return errors


if __name__ == '__main__':
    ''' Returns number of violations found '''
    sys.exit(main(sys.argv))
