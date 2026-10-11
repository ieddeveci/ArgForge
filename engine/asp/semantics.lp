#program base.

{ in(X) } :- arg(X).

out(X) :- att(Y,X), in(Y).

:- in(X), in(Y), conf(X,Y), cf_or_more.

cf_or_more :- semantics(conflict_free).
cf_or_more :- semantics(naive).
cf_or_more :- semantics(admissible).
cf_or_more :- semantics(complete).
cf_or_more :- semantics(stable).
cf_or_more :- semantics(preferred).
cf_or_more :- semantics(grounded).

adm_or_more :- semantics(admissible).
adm_or_more :- semantics(complete).
adm_or_more :- semantics(stable).
adm_or_more :- semantics(preferred).
adm_or_more :- semantics(grounded).

:- in(X), att(Y,X), not out(Y), adm_or_more.

comp_or_more :- semantics(complete).
comp_or_more :- semantics(preferred).
comp_or_more :- semantics(grounded).

undefended(X) :- arg(X), att(Y,X), not out(Y).
:- arg(X), not in(X), not undefended(X), comp_or_more.

:- arg(X), not in(X), not out(X), semantics(stable).

#show in/1.

#heuristic in(X) : arg(X), maximise. [1,true]
#heuristic in(X) : arg(X), minimise. [1,false]

range(X) :- in(X).
range(X) :- out(X).
#heuristic range(X) : arg(X), maximise_range. [1,true]
#show range/1.
