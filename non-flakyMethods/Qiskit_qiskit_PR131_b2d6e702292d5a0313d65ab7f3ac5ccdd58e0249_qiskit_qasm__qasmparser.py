# -*- coding: utf-8 -*-

# Copyright 2017 IBM RESEARCH. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =============================================================================

"""
OPENQASM parser.
"""
import math
import tempfile

import ply.yacc as yacc

from ._qasmlexer import QasmLexer
from ._qasmerror import QasmError
from . import _node as node


class QasmParser(object):
    """OPENQASM Parser."""

    def __init__(self, filename):
        """Create the parser."""
        if filename is None:
            filename = ""
        self.lexer = QasmLexer(filename)
        self.tokens = self.lexer.tokens
        # For yacc, also, write_tables = Bool and optimize = Bool
        parse_dir = tempfile.gettempdir()
        self.parser = yacc.yacc(module=self, debug=False, outputdir=parse_dir)
        self.qasm = None
        self.parse_deb = False
        self.global_symtab = {}                          # global symtab
        self.current_symtab = self.global_symtab         # top of symbol stack
        self.symbols = []                                # symbol stack
        self.external_functions = ['sin', 'cos', 'tan', 'exp', 'ln', 'sqrt']

    def update_symtab(self, obj):
        """Update a node in the symbol table.

        Everything in the symtab must be a node with these attributes:
        name - the string name of the object
        type - the string type of the object
        line - the source line where the type was first found
        file - the source file where the type was first found
        """
        if obj.name in self.current_symtab:
            prev = self.current_symtab[obj.name]
            raise QasmError("Duplicate declaration for", obj.type + " '"
                                + obj.name + "' at line", str(obj.line)
                                + ', file', obj.file
                                + '.\nPrevious occurence at line',
                                str(prev.line) + ', file', prev.file)
        self.current_symtab[obj.name] = obj

    def verify_declared_bit(self, obj):
        """Verify a qubit id against the gate prototype."""
        # We are verifying gate args against the formal parameters of a
        # gate prototype.
        if obj.name not in self.current_symtab:
            raise QasmError("Cannot find symbol '" + obj.name
                                + "' in argument list for gate, line",
                                str(obj.line), 'file', obj.file)

        # This insures the thing is from the bitlist and not from the
        # argument list.
        sym = self.current_symtab[obj.name]
        if not (sym.type == 'id' and sym.is_bit):
            raise QasmError("Bit", obj.name,
                                'is not declared as a bit in the gate.')

    def verify_bit_list(self, obj):
        """Verify each qubit in a list of ids."""
        # We expect the object to be a bitlist or an idlist, we don't care.
        # We will iterate it and ensure everything in it is declared as a bit,
        # and throw if not.
        for children in obj.children:
            self.verify_declared_bit(children)

    def verify_exp_list(self, obj):
        """Verify each expression in a list."""
        # A tad harder.  This is a list of expressions each of which could be
        # the head of a tree. We need to recursively walk each of these and
        # ensure that any Id elements resolve to the current stack.
        #
        # I believe we only have to look at the current symtab.
        if obj.children is not None:
            for children in obj.children:
                if isinstance(children, node.Id):
                    if children.name in self.external_functions:
                        continue

                    if children.name not in self.current_symtab:
                        raise QasmError("Argument '" + children.name
                                            + "' in expression cannot be "
                                            + "found, line", str(children.line),
                                            "file", children.file)
                else:
                    if hasattr(children, "children"):
                        self.verify_exp_list(children)

    def verify_as_gate(self, obj, bitlist, arglist=None):
        """Verify a user defined gate call."""
        if obj.name not in self.global_symtab:
            raise QasmError("Cannot find gate definition for '" + obj.name
                                + "', line", str(obj.line), 'file', obj.file)
        g_sym = self.global_symtab[obj.name]
        if not (g_sym.type == 'gate' or g_sym.type == 'opaque'):
            raise QasmError("'" + obj.name + "' is used as a gate "
                                + "or opaque call but the symbol is neither;"
                                + " it is a '" + g_sym.type + "' line",
                                str(obj.line), 'file', obj.file)

        if g_sym.n_bits() != bitlist.size():
            raise QasmError("Gate or opaque call to '" + obj.name
                                + "' uses", str(bitlist.size()),
                                "qubits but is declared for",
                                str(g_sym.n_bits()), "qubits", "line",
                                str(obj.line), 'file', obj.file)

        if arglist:
            if g_sym.n_args() != arglist.size():
                raise QasmError("Gate or opaque call to '" + obj.name
                                    + "' uses", str(arglist.size()),
                                    "qubits but is declared for",
                                    str(g_sym.n_args()), "qubits", "line",
                                    str(obj.line), 'file', obj.file)
        else:
            if g_sym.n_args() > 0:
                raise QasmError("Gate or opaque call to '" + obj.name
                                    + "' has no arguments but is declared for",
                                    str(g_sym.n_args()), "qubits", "line",
                                    str(obj.line), 'file', obj.file)

    def verify_reg(self, obj, object_type):
        """Verify a register."""
        # How to verify:
        #    types must match
        #    indexes must be checked
        if obj.name not in self.global_symtab:
            raise QasmError('Cannot find definition for', object_type, "'"
                                + obj.name + "'", 'at line', str(obj.line),
                                'file', obj.file)

        g_sym = self.global_symtab[obj.name]

        if g_sym.type != object_type:
            raise QasmError("Type for '" + g_sym.name + "' should be '"
                                + object_type + "' but was found to be '" + g_sym.type
                                + "'", "line", str(obj.line), "file", obj.file)

        if obj.type == 'indexed_id':
            bound = g_sym.index
            ndx = obj.index
            if ndx < 0 or ndx >= bound:
                raise QasmError("Register index for '" + g_sym.name
                                    + "' out of bounds. Index is", str(ndx),
                                    "bound is 0 <= index <", str(bound),
                                    "at line", str(obj.line), "file", obj.file)

    def verify_reg_list(self, obj, object_type):
        """Verify a list of registers."""
        # We expect the object to be a bitlist or an idlist, we don't care.
        # We will iterate it and ensure everything in it is declared as a bit,
        # and throw if not.
        for children in obj.children:
            self.verify_reg(children, object_type)

    def id_tuple_list(self, id_node):
        """Return a list of (name, index) tuples for this id node."""
        assert id_node.type == "id", "internal error, id_tuple_list"
        bit_list = []
        try:
            g_sym = self.current_symtab[id_node.name]
        except KeyError:
            g_sym = self.global_symtab[id_node.name]
        if g_sym.type == "qreg" or g_sym.type == "creg":
            # Return list of (name, idx) for reg ids
            for idx in range(g_sym.index):
                bit_list.append((id_node.name, idx))
        else:
            # Return (name, -1) for other ids
            bit_list.append((id_node.name, -1))
        return bit_list

    def verify_distinct(self, list_of_nodes):
        """Check that objects in list_of_nodes represent distinct (qu)bits.

        list_of_nodes is a list containing nodes of type id, indexed_id,
        primary_list, or id_list. We assume these are all the same type
        'qreg' or 'creg'.
        This method raises an exception if list_of_nodes refers to the
        same object more than once.
        """
        bit_list = []
        line_number = -1
        filename = ""
        for node in list_of_nodes:
            # id node: add all bits in register or (name, -1) for id
            if node.type == "id":
                bit_list.extend(self.id_tuple_list(node))
                line_number = node.line
                filename = node.file
            # indexed_id: add the bit
            elif node.type == "indexed_id":
                bit_list.append((node.name, node.index))
                line_number = node.line
                filename = node.file
            # primary_list: for each id or indexed_id child, add
            elif node.type == "primary_list":
                for child in node.children:
                    if child.type == "id":
                        bit_list.extend(self.id_tuple_list(child))
                    else:
                        bit_list.append((child.name, child.index))
                    line_number = child.line
                    filename = child.file
            # id_list: for each id, add
            elif node.type == "id_list":
                for child in node.children:
                    bit_list.extend(self.id_tuple_list(child))
                    line_number = child.line
                    filename = child.file
            else:
                assert False, "internal error, verify_distinct"
        if len(bit_list) != len(set(bit_list)):
            raise QasmError("duplicate identifiers at line %d file %s"
                                % (line_number, filename))

    def pop_scope(self):
        """Return to the previous scope."""
        self.current_symtab = self.symbols.pop()

    def push_scope(self):
        """Enter a new scope."""
        self.symbols.append(self.current_symtab)
        self.current_symtab = {}

    # ---- Begin the PLY parser ----
    start = 'main'

    def p_main(self, program):
        '''
            main : program
        '''
        self.qasm = program[1]

    # ----------------------------------------
    #  program : statement
    #          | program statement
    # ----------------------------------------
    def p_program_0(self, program):
        '''
           program : statement
        '''
        program[0] = node.Program([program[1]])

    def p_program_1(self, program):
        '''
           program : program statement
        '''
        program[0] = program[1]
        program[0].add_child(program[2])

    # ----------------------------------------
    #  statement : decl
    #            | quantum_op ';'
    #            | magic ';'
    # ----------------------------------------
    def p_statement(self, program):
        '''
           statement : decl
                     | quantum_op ';'
                     | magic ';'
                     | ignore
                     | quantum_op error
                     | magic error
        '''
        if len(program) > 2:
            if program[2] != ';':
                raise QasmError("Missing ';' at end of statement; "
                                    + "received", str(program[2].value))
        program[0] = program[1]

    def p_magic(self, program):
        '''
           magic : MAGIC REAL
        '''
        program[0] = node.Magic([node.Real(program[2])])

    def p_magic_0(self, program):
        '''
           magic : MAGIC error
        '''
        magic = "2.0;"
        raise QasmError("Invalid magic string. Expected '" + magic
                            + "'.  Is the semicolon missing?")

    # ----------------------------------------
    #  id : ID
    # ----------------------------------------
    def p_id(self, program):
        '''
           id : ID
        '''
        program[0] = program[1]

    def p_id_e(self, program):
        '''
           id : error
        '''
        raise QasmError("Expected an ID, received '"
                            + str(program[1].value) + "'")

    # ----------------------------------------
    #  indexed_id : ID [ int ]
    # ----------------------------------------
    def p_indexed_id(self, program):
        '''
           indexed_id : id '[' NNINTEGER ']'
                      | id '[' NNINTEGER error
                      | id '[' error
        '''
        if len(program) == 4:
            raise QasmError("Expecting an integer index; received",
                                str(program[3].value))
        if program[4] != ']':
            raise QasmError("Missing ']' in indexed ID; received",
                                str(program[4].value))
        program[0] = node.IndexedId([program[1], node.Int(program[3])])

    # ----------------------------------------
    #  primary : id
    #          | indexed_id
    # ----------------------------------------
    def p_primary(self, program):
        '''
           primary : id
                   | indexed_id
        '''
        program[0] = program[1]

    # ----------------------------------------
    #  id_list : id
    #          | id_list ',' id
    # ----------------------------------------
    def p_id_list_0(self, program):
        '''
           id_list : id
        '''
        program[0] = node.IdList([program[1]])

    def p_id_list_1(self, program):
        '''
           id_list : id_list ',' id
        '''
        program[0] = program[1]
        program[0].add_child(program[3])

    # ----------------------------------------
    #  gate_id_list : id
    #               | gate_id_list ',' id
    # ----------------------------------------
    def p_gate_id_list_0(self, program):
        '''
           gate_id_list : id
        '''
        program[0] = node.IdList([program[1]])
        self.update_symtab(program[1])

    def p_gate_id_list_1(self, program):
        '''
           gate_id_list : gate_id_list ',' id
        '''
        program[0] = program[1]
        program[0].add_child(program[3])
        self.update_symtab(program[3])

    # ----------------------------------------
    #  bit_list : bit
    #           | bit_list ',' bit
    # ----------------------------------------
    def p_bit_list_0(self, program):
        '''
           bit_list : id
        '''
        program[0] = node.IdList([program[1]])
        program[1].is_bit = True
        self.update_symtab(program[1])

    def p_bit_list_1(self, program):
        '''
           bit_list : bit_list ',' id
        '''
        program[0] = program[1]
        program[0].add_child(program[3])
        program[3].is_bit = True
        self.update_symtab(program[3])

    # ----------------------------------------
    #  primary_list : primary
    #               | primary_list ',' primary
    # ----------------------------------------
    def p_primary_list_0(self, program):
        '''
           primary_list : primary
        '''
        program[0] = node.PrimaryList([program[1]])

    def p_primary_list_1(self, program):
        '''
           primary_list : primary_list ',' primary
        '''
        program[0] = program[1]
        program[1].add_child(program[3])

    # ----------------------------------------
    #  decl : qreg_decl
    #       | creg_decl
    #       | gate_decl
    # ----------------------------------------
    def p_decl(self, program):
        '''
           decl : qreg_decl ';'
                | creg_decl ';'
                | qreg_decl error
                | creg_decl error
                | gate_decl
        '''
        if len(program) > 2:
            if program[2] != ';':
                raise QasmError("Missing ';' in qreg or creg declaraton."
                                    + " Instead received '" + program[2].value + "'")
        program[0] = program[1]

    # ----------------------------------------
    #  qreg_decl : QREG indexed_id
    # ----------------------------------------
    def p_qreg_decl(self, program):
        '''
           qreg_decl : QREG indexed_id
        '''
        program[0] = node.Qreg([program[2]])
        if program[2].name in self.external_functions:
            raise QasmError("QREG names cannot be reserved words. "
                                + "Received '" + program[2].name + "'")
        if program[2].index == 0:
            raise QasmError("QREG size must be positive")
        self.update_symtab(program[0])

    def p_qreg_decl_e(self, program):
        '''
           qreg_decl : QREG error
        '''
        raise QasmError("Expecting indexed id (ID[int]) in QREG"
                            + " declaration; received", program[2].value)

    # ----------------------------------------
    #  creg_decl : QREG indexed_id
    # ----------------------------------------
    def p_creg_decl(self, program):
        '''
           creg_decl : CREG indexed_id
        '''
        program[0] = node.Creg([program[2]])
        if program[2].name in self.external_functions:
            raise QasmError("CREG names cannot be reserved words. "
                                + "Received '" + program[2].name + "'")
        if program[2].index == 0:
            raise QasmError("CREG size must be positive")
        self.update_symtab(program[0])

    def p_creg_decl_e(self, program):
        '''
           creg_decl : CREG error
        '''
        raise QasmError("Expecting indexed id (ID[int]) in CREG"
                            + " declaration; received", program[2].value)

    # Gate_body will throw if there are errors, so we don't need to cover
    # that here. Same with the id_lists - if they are not legal, we die
    # before we get here
    #
    # ----------------------------------------
    #  gate_decl : GATE id gate_scope                      bit_list gate_body
    #            | GATE id gate_scope '(' ')'              bit_list gate_body
    #            | GATE id gate_scope '(' gate_id_list ')' bit_list gate_body
    #
    # ----------------------------------------
    def p_gate_decl_0(self, program):
        '''
           gate_decl : GATE id gate_scope bit_list gate_body
        '''
        program[0] = node.Gate([program[2], program[4], program[5]])
        if program[2].name in self.external_functions:
            raise QasmError("GATE names cannot be reserved words. "
                                + "Received '" + program[2].name + "'")
        self.pop_scope()
        self.update_symtab(program[0])

    def p_gate_decl_1(self, program):
        '''
           gate_decl : GATE id gate_scope '(' ')' bit_list gate_body
        '''
        program[0] = node.Gate([program[2], program[6], program[7]])
        if program[2].name in self.external_functions:
            raise QasmError("GATE names cannot be reserved words. "
                                + "Received '" + program[2].name + "'")
        self.pop_scope()
        self.update_symtab(program[0])

    def p_gate_decl_2(self, program):
        '''
        gate_decl : GATE id gate_scope '(' gate_id_list ')' bit_list gate_body
        '''
        program[0] = node.Gate(
            [program[2], program[5], program[7], program[8]])
        if program[2].name in self.external_functions:
            raise QasmError("GATE names cannot be reserved words. "
                                + "Received '" + program[2].name + "'")
        self.pop_scope()
        self.update_symtab(program[0])

    def p_gate_scope(self, program):
        '''
           gate_scope :
        '''
        self.push_scope()

    # ----------------------------------------
    #  gate_body : '{' gate_op_list '}'
    #            | '{' '}'
    #
    #            | '{' gate_op_list error
    #            | '{' error
    #
    # Error handling: gete_op will throw if there's a problem so we won't
    #                 get here with in the gate_op_list
    # ----------------------------------------
    def p_gate_body_0(self, program):
        '''
           gate_body : '{' '}'
        '''
        if program[2] != '}':
            raise QasmError("Missing '}' in gate definition; received'"
                                + str(program[2].value) + "'")
        program[0] = node.GateBody(None)

    def p_gate_body_1(self, program):
        '''
           gate_body : '{' gate_op_list '}'
        '''
        program[0] = node.GateBody(program[2])

    # ----------------------------------------
    #  gate_op_list : gate_op
    #               | gate_op_ist gate_op
    #
    # Error handling: gete_op will throw if there's a problem so we won't
    #                 get here with errors
    # ----------------------------------------
    def p_gate_op_list_0(self, program):
        '''
            gate_op_list : gate_op
        '''
        program[0] = [program[1]]

    def p_gate_op_list_1(self, program):
        '''
            gate_op_list : gate_op_list gate_op
        '''
        program[0] = program[1]
        program[0].append(program[2])

    # ----------------------------------------
    # These are for use outside of gate_bodies and allow
    # indexed ids everywhere.
    #
    # unitary_op : U '(' exp_list ')'  primary
    #            | CX                  primary ',' primary
    #            | id                  pirmary_list
    #            | id '(' ')'          primary_list
    #            | id '(' exp_list ')' primary_list
    #
    # Note that it might not be unitary - this is the mechanism that
    # is also used to invoke calls to 'opaque'
    # ----------------------------------------
    def p_unitary_op_0(self, program):
        '''
          unitary_op : U '(' exp_list ')' primary
        '''
        program[0] = node.UniversalUnitary([program[3], program[5]])
        self.verify_reg(program[5], 'qreg')
        self.verify_exp_list(program[3])

    def p_unitary_op_1(self, program):
        '''
        unitary_op : CX primary ',' primary
        '''
        program[0] = node.Cnot([program[2], program[4]])
        self.verify_reg(program[2], 'qreg')
        self.verify_reg(program[4], 'qreg')
        self.verify_distinct([program[2], program[4]])
        # TODO: check that if both primary are id, same size
        # TODO: this needs to be checked in other cases too

    def p_unitary_op_2(self, program):
        '''
        unitary_op : id primary_list
        '''
        program[0] = node.CustomUnitary([program[1], program[2]])
        self.verify_as_gate(program[1], program[2])
        self.verify_reg_list(program[2], 'qreg')
        self.verify_distinct([program[2]])

    def p_unitary_op_3(self, program):
        '''
        unitary_op : id '(' ')' primary_list
        '''
        program[0] = node.CustomUnitary([program[1], program[4]])
        self.verify_as_gate(program[1], program[4])
        self.verify_reg_list(program[4], 'qreg')
        self.verify_distinct([program[4]])

    def p_unitary_op_4(self, program):
        '''
        unitary_op : id '(' exp_list ')' primary_list
        '''
        program[0] = node.CustomUnitary([program[1], program[3], program[5]])
        self.verify_as_gate(program[1], program[5], arglist=program[3])
        self.verify_reg_list(program[5], 'qreg')
        self.verify_exp_list(program[3])
        self.verify_distinct([program[5]])

    # ----------------------------------------
    # This is a restricted set of "quantum_op" which also
    # prohibits indexed ids, for use in a gate_body
    #
    # gate_op : U '(' exp_list ')'  id         ';'
    #         | CX                  id ',' id  ';'
    #         | id                  id_list    ';'
    #         | id '(' ')'          id_list    ';'
    #         | id '(' exp_list ')' id_list    ';'
    #         | BARRIER id_list                ';'
    # ----------------------------------------
    def p_gate_op_0(self, program):
        '''
        gate_op : U '(' exp_list ')' id ';'
        '''
        program[0] = node.UniversalUnitary([program[3], program[5]])
        self.verify_declared_bit(program[5])
        self.verify_exp_list(program[3])

    def p_gate_op_0e1(self, p):
        '''
        gate_op : U '(' exp_list ')' error
        '''
        raise QasmError("Invalid U inside gate definition. "
                            + "Missing bit id or ';'")

    def p_gate_op_0e2(self, program):
        '''
        gate_op : U '(' exp_list error
        '''
        raise QasmError("Missing ')' in U invocation in gate definition.")

    def p_gate_op_1(self, program):
        '''
        gate_op : CX id ',' id ';'
        '''
        program[0] = node.Cnot([program[2], program[4]])
        self.verify_declared_bit(program[2])
        self.verify_declared_bit(program[4])
        self.verify_distinct([program[2], program[4]])

    def p_gate_op_1e1(self, program):
        '''
        gate_op : CX error
        '''
        raise QasmError("Invalid CX inside gate definition. "
                            + "Expected an ID or ',', received '"
                            + str(program[2].value) + "'")

    def p_gate_op_1e2(self, program):
        '''
        gate_op : CX id ',' error
        '''
        raise QasmError("Invalid CX inside gate definition. "
                            + "Expected an ID or ';', received '"
                            + str(program[4].value) + "'")

    def p_gate_op_2(self, program):
        '''
        gate_op : id id_list ';'
        '''
        program[0] = node.CustomUnitary([program[1], program[2]])
        # To verify:
        # 1. id is declared as a gate in global scope
        # 2. everything in the id_list is declared as a bit in local scope
        self.verify_as_gate(program[1], program[2])
        self.verify_bit_list(program[2])
        self.verify_distinct([program[2]])

    def p_gate_op_2e(self, program):
        '''
        gate_op : id  id_list error
        '''
        raise QasmError("Invalid gate invocation inside gate definition.")

    def p_gate_op_3(self, program):
        '''
        gate_op : id '(' ')' id_list ';'
        '''
        program[0] = node.CustomUnitary([program[1], program[4]])
        self.verify_as_gate(program[1], program[4])
        self.verify_bit_list(program[4])
        self.verify_distinct([program[4]])

    def p_gate_op_4(self, program):
        '''
        gate_op : id '(' exp_list ')' id_list ';'
        '''
        program[0] = node.CustomUnitary([program[1], program[3], program[5]])
        self.verify_as_gate(program[1], program[5], arglist=program[3])
        self.verify_bit_list(program[5])
        self.verify_exp_list(program[3])
        self.verify_distinct([program[5]])

    def p_gate_op_4e0(self, program):
        '''
        gate_op : id '(' ')'  error
        '''
        raise QasmError("Invalid bit list inside gate definition or"
                            + " missing ';'")

    def p_gate_op_4e1(self, program):
        '''
        gate_op : id '('   error
        '''
        raise QasmError("Unmatched () for gate invocation inside gate"
                            + " invocation.")

    def p_gate_op_5(self, program):
        '''
        gate_op : BARRIER id_list ';'
        '''
        program[0] = node.Barrier([program[2]])
        self.verify_bit_list(program[2])
        self.verify_distinct([program[2]])

    def p_gate_op_5e(self, program):
        '''
        gate_op : BARRIER error
        '''
        raise QasmError("Invalid barrier inside gate definition.")

    # ----------------------------------------
    # opaque : OPAQUE id gate_scope                      bit_list
    #        | OPAQUE id gate_scope '(' ')'              bit_list
    #        | OPAQUE id gate_scope '(' gate_id_list ')' bit_list
    #
    # These are like gate declaratons only wihtout a body.
    # ----------------------------------------
    def p_opaque_0(self, program):
        '''
           opaque : OPAQUE id gate_scope bit_list
        '''
        # TODO: Review Opaque function
        program[0] = node.Opaque([program[2], program[4]])
        if program[2].name in self.external_functions:
            raise QasmError("OPAQUE names cannot be reserved words. "
                                + "Received '" + program[2].name + "'")
        self.pop_scope()
        self.update_symtab(program[0])

    def p_opaque_1(self, program):
        '''
           opaque : OPAQUE id gate_scope '(' ')' bit_list
        '''
        program[0] = node.Opaque([program[2], program[6]])
        self.pop_scope()
        self.update_symtab(program[0])

    def p_opaque_2(self, program):
        '''
           opaque : OPAQUE id gate_scope '(' gate_id_list ')' bit_list
        '''
        program[0] = node.Opaque([program[2], program[5], program[7]])
        if program[2].name in self.external_functions:
            raise QasmError("OPAQUE names cannot be reserved words. "
                                + "Received '" + program[2].name + "'")
        self.pop_scope()
        self.update_symtab(program[0])

    def p_opaque_1e(self, program):
        '''
           opaque : OPAQUE id gate_scope '(' error
        '''
        raise QasmError("Poorly formed OPAQUE statement.")

    # ----------------------------------------
    # measure : MEASURE primary ASSIGN primary
    # ----------------------------------------
    def p_measure(self, program):
        '''
           measure : MEASURE primary ASSIGN primary
        '''
        program[0] = node.Measure([program[2], program[4]])
        self.verify_reg(program[2], 'qreg')
        self.verify_reg(program[4], 'creg')

    def p_measure_e(self, program):
        '''
           measure : MEASURE primary error
        '''
        raise QasmError("Illegal measure statement." +
                            str(program[3].value))

    # ----------------------------------------
    # barrier : BARRIER primary_list
    #
    # Errors are covered by handling erros in primary_list
    # ----------------------------------------
    def p_barrier(self, program):
        '''
        barrier : BARRIER primary_list
        '''
        program[0] = node.Barrier([program[2]])
        self.verify_reg_list(program[2], 'qreg')
        self.verify_distinct([program[2]])

    # ----------------------------------------
    # reset : RESET primary
    # ----------------------------------------
    def p_reset(self, program):
        '''
        reset : RESET primary
        '''
        program[0] = node.Reset([program[2]])
        self.verify_reg(program[2], 'qreg')

    # ----------------------------------------
    # IF '(' ID MATCHES NNINTEGER ')' quantum_op
    # ----------------------------------------
    def p_if(self, program):
        '''
        if : IF '(' id MATCHES NNINTEGER ')' quantum_op
        if : IF '(' id error
        if : IF '(' id MATCHES error
        if : IF '(' id MATCHES NNINTEGER error
        if : IF error
        '''
        if len(program) == 3:
            raise QasmError("Ill-formed IF statement. Perhaps a"
                                + " missing '('?")
        if len(program) == 5:
            raise QasmError("Ill-formed IF statement.  Expected '==', "
                                + "received '" + str(program[4].value))
        if len(program) == 6:
            raise QasmError("Ill-formed IF statement.  Expected a number, "
                                + "received '" + str(program[5].value))
        if len(program) == 7:
            raise QasmError("Ill-formed IF statement, unmatched '('")

        if program[7].type == 'if':
            raise QasmError("Nested IF statements not allowed")
        if program[7].type == 'barrier':
            raise QasmError("barrier not permitted in IF statement")

        program[0] = node.If([program[3], node.Int(program[5]), program[7]])

    # ----------------------------------------
    # These are all the things you can have outside of a gate declaration
    #        quantum_op : unitary_op
    #                   | opaque
    #                   | measure
    #                   | reset
    #                   | barrier
    #                   | if
    #
    # ----------------------------------------
    def p_quantum_op(self, program):
        '''
            quantum_op : unitary_op
                       | opaque
                       | measure
                       | barrier
                       | reset
                       | if
        '''
        program[0] = program[1]

    # ----------------------------------------
    # unary : NNINTEGER
    #       | REAL
    #       | PI
    #       | ID
    #       | '(' expression ')'
    #       | id '(' expression ')'
    #
    # We will trust 'expression' to throw before we have to handle it here
    # ----------------------------------------
    def p_unary_0(self, program):
        '''
           unary : NNINTEGER
        '''
        program[0] = node.Int(program[1])

    def p_unary_1(self, program):
        '''
           unary : REAL
        '''
        program[0] = node.Real(program[1])

    def p_unary_2(self, program):
        '''
           unary : PI
        '''
        program[0] = node.Real(math.pi)

    def p_unary_3(self, program):
        '''
           unary : id
        '''
        program[0] = program[1]

    def p_unary_4(self, program):
        '''
           unary : '(' expression ')'
        '''
        program[0] = program[2]

    def p_unary_6(self, program):
        '''
           unary : id '(' expression ')'
        '''
        # note this is a semantic check, not syntactic
        if program[1].name not in self.external_functions:
            raise QasmError("Illegal external function call: ",
                                str(program[1].name))
        program[0] = node.External([program[1], program[3]])

    # ----------------------------------------
    # Prefix
    # ----------------------------------------
    def p_prefix_expression_0(self, program):
        '''
           prefix_expression : unary
        '''
        program[0] = program[1]

    def p_prefix_expression_1(self, program):
        '''
           prefix_expression : '+' prefix_expression
                             | '-' prefix_expression
        '''
        program[0] = node.Prefix([node.UnaryOperator(program[1]), program[2]])

    def p_additive_expression_0(self, program):
        '''
            additive_expression : prefix_expression
        '''
        program[0] = program[1]

    def p_additive_expression_1(self, program):
        '''
            additive_expression : additive_expression '+' prefix_expression
                                | additive_expression '-' prefix_expression
        '''
        program[0] = node.BinaryOp([node.BinaryOperator(program[2]),
                                    program[1], program[3]])

    def p_multiplicative_expression_0(self, program):
        '''
            multiplicative_expression : additive_expression
        '''
        program[0] = program[1]

    def p_multiplicative_expression_1(self, program):
        '''
        multiplicative_expression : multiplicative_expression '*' additive_expression
                                  | multiplicative_expression '/' additive_expression
        '''
        program[0] = node.BinaryOp([node.BinaryOperator(program[2]),
                                    program[1], program[3]])

    def p_expression_0(self, program):
        '''
            expression : multiplicative_expression
        '''
        program[0] = program[1]

    def p_expression_1(self, program):
        '''
            expression : expression '^' multiplicative_expression
        '''
        program[0] = node.BinaryOp([node.BinaryOperator(program[2]),
                                    program[1], program[3]])

    # ----------------------------------------
    # exp_list : exp
    #          | exp_list ',' exp
    # ----------------------------------------
    def p_exp_list_0(self, program):
        '''
           exp_list : expression
        '''
        program[0] = node.ExpressionList([program[1]])

    def p_exp_list_1(self, program):
        '''
           exp_list : exp_list ',' expression
        '''
        program[0] = program[1]
        program[0].add_child(program[3])

    def p_ignore(self, program):
        '''
           ignore : STRING
        '''
        # this should never hit but it keeps the insuppressible warnings at bay
        pass

    def p_error(self, program):
        # EOF is a special case because the stupid error token isn't placed
        # on the stack
        if not program:
            raise QasmError("Error at end of file. "
                                + "Perhaps there is a missing ';'")

        col = self.find_column(self.lexer.data, program)
        print("Error near line", str(self.lexer.lineno), 'Column', col)

    def find_column(self, input, token):
        """Compute the column.

        Input is the input text string.
        token is a token instance.
        """
        if token is None:
            return 0
        last_cr = input.rfind('\n', 0, token.lexpos)
        if last_cr < 0:
            last_cr = 0
        column = (token.lexpos - last_cr) + 1
        return column

    def print_tokens(self):
        '''Test method to verify tokenizer.'''
        try:
            while True:
                token = self.lexer.token()
                if not token:
                    break
                # TODO: This isn't really the column, it's the character
                # position.  Need to do backtrack to the nearest \n to get
                # the actual column.
                print('TOKEN:' + str(token) + ":ENDTOKEN", 'at line',
                      token.lineno, 'column', token.lexpos, 'file',
                      self.lexer.filename)
        except QasmError as e:
            print('Exception tokenizing qasm file:', e.msg)

    def parse_debug(self, val):
        """Set the parseDeb field."""
        if val is True:
            self.parseDeb = True
        elif val is False:
            self.parseDeb = False
        else:
            raise QasmError("Illegal debug value '" + str(val)
                                + "' must be True or False.")

    def parse(self, data):
        """Parse some data."""
        self.parser.parse(data, lexer=self.lexer, debug=self.parseDeb)
        if self.qasm is None:
            raise QasmError("Uncaught exception in parser; "
                                + "see previous messages for details.")
        return self.qasm

    def print_tree(self):
        """Print parsed OPENQASM."""
        if self.qasm is not None:
            self.qasm.to_string(0)
        else:
            print("No parsed qasm to print")

    def run(self, data):
        """Parser runner.

        To use this module stand-alone.
        """
        ast = self.parser.parse(data, debug=True)
        self.parser.parse(data, debug=True)
        ast.to_string(0)
