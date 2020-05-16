#! /usr/bin/env python3
"""Simple verilog parser

This parser will take verilog and try to break it down into formal lines of verilog. It is focused on preparing code for the Domain Assignment Checker
"""
import sys
import re

# Delineators for case and if, added to code lines
if_del = ':if:'
case_del = ':case:'

hasalpha_re = re.compile(r'[a-zA-Z]+')
macro_re = re.compile(r'`.*')
tokenizer = re.compile(r'[\S]+')

# These can fail with weird comments (like nested), but should be good enough
comment_line_re = re.compile(r'//.*')
comment_block_re = re.compile(r'/\*.*?\*/', re.DOTALL)

VERBOSE = False


class StrLine(str):
    ''' StrLine class is string class plus line number '''
    def __new__(cls, value, *args, **kwargs):
        return super().__new__(cls, value)

    def __init__(self, string, linenum):
        self.linenum = linenum

    def __add__(self, other):
        return StrLine(str(self) + other, self.linenum)

    def split(self, sep=None, maxsplit=-1):
        pieces = super().split(sep, maxsplit)
        return [StrLine(ii, self.linenum) for ii in pieces]


# Create a super simple parser
def check_endline(token, lines, line):
    if token in [';', 'for', 'endgenerate', 'endfunction']:
        lines.append(StrLine(line, token.linenum))
        if VERBOSE:
            print(f"endLine: {line}")
        line = ""
    return line


def check_token(token, tokens, lines, line):
    if token == "(":
        # remove function names
        if " " in line:
            last_token = line.split()[-1]
            if hasalpha_re.search(last_token):
                line = line.replace(last_token, "")
        tokens, pline = enter_paren(tokens)
        line += pline
    elif token == 'if':
        lines.append(StrLine(line, token.linenum))
        line = ""
        if VERBOSE:
            print(f"if Line: {line}")
        tokens, ilines = enter_if(tokens)
        lines += ilines
    elif token == 'case':
        lines.append(StrLine(line, token.linenum))
        line = ""
        if VERBOSE:
            print(f"casLine: {line}")
        tokens, clines = enter_case(tokens)
        lines += clines
    elif (token == 'begin'):
        lines.append(StrLine(line, token.linenum))
        line = ""
        if VERBOSE:
            print(f"begLine: {line}")
        tokens, klines = enter_keyword(tokens, 'begin', 'end')
        lines += klines
    else:
        line += token + " "
    return tokens, line


def enter_paren(tokens):
    line = "("
    while tokens:
        token = tokens.pop(0)
        if token == "(":
            # remove function names
            if " " in line:
                last_token = line.split()[-1]
                if hasalpha_re.search(last_token):
                    line = line.replace(last_token, "")
            tokens, pline = enter_paren(tokens)
            line += pline
        elif token == ")":
            return tokens, line.strip() + token
        else:
            line += token + " "
        if ("(" in token or ")" in token) and len(token) > 1:
            print(f"Failed to separate parentheses in tokenization: {token}")
            sys.exit(-1)
    return tokens, line


def enter_keyword(tokens, openword="begin", closeword="end"):
    line = ""
    lines = []
    if tokens[0] == ':':
        # Drop label
        tokens = tokens[2:]
    while tokens:
        token = tokens.pop(0)
        if openword == token:
            lines.append(StrLine(line, token.linenum))
            line = ''
            if VERBOSE:
                print(f"keyLine: {line}")
            tokens, klines = enter_keyword(tokens, openword, closeword)
            lines += klines
        elif closeword == token:
            return tokens, lines
        else:
            tokens, line = check_token(token, tokens, lines, line)
        line = check_endline(token, lines, line)
    return tokens, lines


def enter_if(tokens):
    line = ""
    begin_end = False
    # Find 'if' condition
    while tokens:
        token = tokens.pop(0)
        if ("(" in token):
            tokens, condition = enter_paren(tokens)
            break
    # Reached end of 'if' condition
    lines = []
    while tokens:
        token = tokens.pop(0)
        if (token == 'begin'):
            tokens, lines = enter_keyword(tokens, 'begin', 'end')
            break
        else:
            line += token + " "
            if (token == ';'):
                lines = [StrLine(line, token.linenum)]
                break
    cond_lines = [line + f" {if_del} {condition}" for line in lines if line]
    if tokens[0] == 'else':
        token = tokens.pop(0)
        condition = f"! {condition}"
        lines = []
        while tokens:
            token = tokens.pop(0)
            if (token == 'begin'):
                tokens, lines = enter_keyword(tokens, 'begin', 'end')
                break
            else:
                line += token + " "
                if (token == ';'):
                    lines = [StrLine(line, token.linenum)]
                    break
        cond_lines += [line + f" {if_del} {condition}"
                       for line in lines if line]
    return tokens, cond_lines


def enter_case(tokens):
    line = ""
    begin_end = False
    # Find 'case' condition
    while tokens:
        token = tokens.pop(0)
        if ("(" in token):
            tokens, condition = enter_paren(tokens)
            break
    # Reached end of 'case' condition
    lines = []
    while tokens:
        token = tokens.pop(0)
        if (token == 'endcase'):
            break
        tokens, line = check_token(token, tokens, lines, line)
        line = check_endline(token, lines, line)
    cond_lines = [line + f" {case_del} {condition}" for line in lines if line]
    return tokens, cond_lines


def file_to_lines(file_contents):
    ''' Parse file_contents into individual formalized lines of verilog '''
    # Remove comments to avoid false positives
    code = comment_line_re.sub('', file_contents)
    # Preserve line number
    cblocks = comment_block_re.findall(code)
    for cblock in cblocks:
        cnt = cblock.count("\n")
        code = code.replace(cblock, "\n" * cnt)
    # Remove macros, as they can be anything
    code = code.replace('\\\n', '__killed_macro__')
    mblocks = macro_re.findall(code)
    for mblock in mblocks:
        mcnt = mblock.count('__killed_macro__')
        code = code.replace(mblock, "\n" * mcnt)
    # Ensure spaces around key symbols and words for easy token regex
    for kw in ['(', ')', ';', ':']:
        code = code.replace(kw, f' {kw} ')
    for kw in ['begin', 'end', 'if', 'else', 'case', 'endcase', 'for',
               'endgenerate', 'endfunction']:
        # Only match if it's a standalone word
        code = re.sub(rf'(?<!\w){kw}(?!\w)', f' {kw} ', code)
    for kw in ['<=', '=']:
        # Only match if it's a standalone operator
        code = re.sub(rf'(?<![<=>!]){kw}(?![<=>])', f' {kw} ', code)
    # fix ::
    code = code.replace(' :  : ', '::')

    # Break code up into tokens, walk through tokens and build up lines of code
    tokens = tokenizer.findall(code)
    lines = code.splitlines()
    tokens = []
    for linenum in range(len(lines)):
        new = tokenizer.findall(lines[linenum])
        for token in new:
            tokens.append(StrLine(token, linenum + 1))
    lines = []
    line = ""
    while tokens:
        token = tokens.pop(0)
        tokens, line = check_token(token, tokens, lines, line)
        line = check_endline(token, lines, line)
    return [line for line in lines if line]


if __name__ == '__main__':
    ''' Pass filename in as argument and get raw strings out '''
    with open(sys.argv[1]) as fh:
        file_contents = fh.read()
    lines = file_to_lines(file_contents)
    for line in lines:
        print("*" + line)
