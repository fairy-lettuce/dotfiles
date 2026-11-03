; Indent queries for C#.
;
; Helix ships no indents.scm for c-sharp (`hx --health c-sharp` reports it as
; missing), so `=` and newline-in-insert-mode fall back to copying the previous
; line's indent. This file provides the structural rules.
;
; Installed into the Helix runtime directory by tools/setup-helix-csharp.ps1.

; Anything delimited by a brace, paren or bracket indents its contents.
[
  (block)
  (declaration_list)
  (enum_member_declaration_list)
  (accessor_list)
  (switch_body)
  (switch_section)
  (switch_expression)
  (initializer_expression)
  (anonymous_object_creation_expression)
  (argument_list)
  (bracketed_argument_list)
  (attribute_argument_list)
  (attribute_list)
  (parameter_list)
  (bracketed_parameter_list)
  (type_parameter_list)
  (type_argument_list)
  (array_rank_specifier)
  (list_pattern)
  (property_pattern_clause)
  (positional_pattern_clause)
  (interpolation)
] @indent

[
  "}"
  ")"
  "]"
] @outdent

; Bodies written without braces still indent one level:
;   if (x)
;       DoThing();
(if_statement
  consequence: (_) @indent
  (#not-kind-eq? @indent "block"))

; `else if` chains must not indent, so exclude if_statement here.
(if_statement
  alternative: (_) @indent
  (#not-kind-eq? @indent "block")
  (#not-kind-eq? @indent "if_statement"))

(for_statement body: (_) @indent (#not-kind-eq? @indent "block"))
(while_statement body: (_) @indent (#not-kind-eq? @indent "block"))
(foreach_statement body: (_) @indent (#not-kind-eq? @indent "block"))
(do_statement body: (_) @indent (#not-kind-eq? @indent "block"))
(using_statement body: (_) @indent (#not-kind-eq? @indent "block"))

; Expression-bodied members: `int X => ...;` continued on the next line.
(arrow_expression_clause) @indent
