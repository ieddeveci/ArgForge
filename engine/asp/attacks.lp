stronger_rule(S,W) :- rule_pref(S,W).
stronger_rule(S,W) :- rule_pref(S,M), stronger_rule(M,W).
stronger_prem(S,W) :- prem_pref(S,W).
stronger_prem(S,W) :- prem_pref(S,M), stronger_prem(M,W).

weaker_rule(W,S) :- stronger_rule(S,W).
weaker_prem(W,S) :- stronger_prem(S,W).

raw_attack(A,B,rebut) :-
    arg(A), subarg(B,BP), top_kind(BP,defeasible),
    conc(A,CA), conc(BP,CB), conflict(CA,CB).

raw_attack(A,B,undercut) :-
    arg(A), subarg(B,BP), top_kind(BP,defeasible),
    top_rule(BP,R), rule_literal(R,RL),
    conc(A,CA), conflict(CA,RL).

raw_attack(A,B,undermine) :-
    arg(A), ord_premise(B,P), conc(A,CA), conflict(CA,P).

has_lastdef(A) :- last_def_rule(A,_).
has_ordprem(A) :- ord_premise(A,_).

ll_eli(A,B) :- ordering(last_link), comparison(elitist),
               arg(A), arg(B), has_lastdef(A), not has_lastdef(B).
ll_eli(A,B) :- ordering(last_link), comparison(elitist),
               last_def_rule(A,R), has_lastdef(B),
               not ll_eli_fail(A,B,R).
ll_eli_fail(A,B,R) :- last_def_rule(A,R), last_def_rule(B,S),
                      not weaker_rule(R,S).

ll_dem(A,B) :- ordering(last_link), comparison(democratic),
               arg(A), arg(B), has_lastdef(A), not has_lastdef(B).
ll_dem(A,B) :- ordering(last_link), comparison(democratic),
               has_lastdef(A), has_lastdef(B),
               not ll_dem_fail(A,B).
ll_dem_fail(A,B) :- last_def_rule(A,R), has_lastdef(B),
                    not ll_dem_wit(A,B,R).
ll_dem_wit(A,B,R) :- last_def_rule(A,R), last_def_rule(B,S), weaker_rule(R,S).

llp_eli(A,B) :- ordering(last_link), comparison(elitist),
                arg(A), arg(B), not has_lastdef(A), not has_lastdef(B),
                has_ordprem(A), not has_ordprem(B).
llp_eli(A,B) :- ordering(last_link), comparison(elitist),
                not has_lastdef(A), not has_lastdef(B),
                ord_premise(A,P), has_ordprem(B), not llp_eli_fail(A,B,P).
llp_eli_fail(A,B,P) :- ord_premise(A,P), ord_premise(B,Q), not weaker_prem(P,Q).

llp_dem(A,B) :- ordering(last_link), comparison(democratic),
                arg(A), arg(B), not has_lastdef(A), not has_lastdef(B),
                has_ordprem(A), not has_ordprem(B).
llp_dem(A,B) :- ordering(last_link), comparison(democratic),
                not has_lastdef(A), not has_lastdef(B),
                has_ordprem(A), has_ordprem(B), not llp_dem_fail(A,B).
llp_dem_fail(A,B) :- ord_premise(A,P), has_ordprem(B), not llp_dem_wit(A,B,P).
llp_dem_wit(A,B,P) :- ord_premise(A,P), ord_premise(B,Q), weaker_prem(P,Q).

has_defrule(A) :- def_rule(A,_).

wl_rule_eli(A,B) :- arg(A), arg(B), has_defrule(A), not has_defrule(B).
wl_rule_eli(A,B) :- def_rule(A,R), has_defrule(B), not wl_rule_eli_fail(A,B,R).
wl_rule_eli_fail(A,B,R) :- def_rule(A,R), def_rule(B,S), not weaker_rule(R,S).

wl_rule_dem(A,B) :- arg(A), arg(B), has_defrule(A), not has_defrule(B).
wl_rule_dem(A,B) :- has_defrule(A), has_defrule(B), not wl_rule_dem_fail(A,B).
wl_rule_dem_fail(A,B) :- def_rule(A,R), has_defrule(B), not wl_rule_dem_wit(A,B,R).
wl_rule_dem_wit(A,B,R) :- def_rule(A,R), def_rule(B,S), weaker_rule(R,S).

wl_prem_eli(A,B) :- arg(A), arg(B), has_ordprem(A), not has_ordprem(B).
wl_prem_eli(A,B) :- ord_premise(A,P), has_ordprem(B), not wl_prem_eli_fail(A,B,P).
wl_prem_eli_fail(A,B,P) :- ord_premise(A,P), ord_premise(B,Q), not weaker_prem(P,Q).

wl_prem_dem(A,B) :- arg(A), arg(B), has_ordprem(A), not has_ordprem(B).
wl_prem_dem(A,B) :- has_ordprem(A), has_ordprem(B), not wl_prem_dem_fail(A,B).
wl_prem_dem_fail(A,B) :- ord_premise(A,P), has_ordprem(B), not wl_prem_dem_wit(A,B,P).
wl_prem_dem_wit(A,B,P) :- ord_premise(A,P), ord_premise(B,Q), weaker_prem(P,Q).

wl_rule(A,B) :- comparison(elitist),    wl_rule_eli(A,B).
wl_rule(A,B) :- comparison(democratic), wl_rule_dem(A,B).
wl_prem(A,B) :- comparison(elitist),    wl_prem_eli(A,B).
wl_prem(A,B) :- comparison(democratic), wl_prem_dem(A,B).

weaker(A,B) :- ordering(weakest_link), arg(A), arg(B),
               not has_defrule(A), not has_defrule(B), wl_prem(A,B).
weaker(A,B) :- ordering(weakest_link), arg(A), arg(B),
               has_defrule2(A,B), not has_ordprem(A), not has_ordprem(B),
               wl_rule(A,B).
weaker(A,B) :- ordering(weakest_link), arg(A), arg(B),
               mixed(A,B), wl_rule(A,B), wl_prem(A,B).
has_defrule2(A,B) :- arg(A), arg(B), has_defrule(A).
has_defrule2(A,B) :- arg(A), arg(B), has_defrule(B).
mixed(A,B) :- arg(A), arg(B), has_defrule2(A,B), has_ordprem(A).
mixed(A,B) :- arg(A), arg(B), has_defrule2(A,B), has_ordprem(B).

weaker(A,B) :- ordering(last_link), comparison(elitist),    ll_eli(A,B).
weaker(A,B) :- ordering(last_link), comparison(democratic), ll_dem(A,B).
weaker(A,B) :- ordering(last_link), comparison(elitist),    llp_eli(A,B).
weaker(A,B) :- ordering(last_link), comparison(democratic), llp_dem(A,B).

defeat(A,B) :- raw_attack(A,B,undercut).
defeat(A,B) :- arg(A), subarg(B,BP), top_kind(BP,defeasible),
               conc(A,CA), conc(BP,CB), contrary_only(CA,CB).
defeat(A,B) :- arg(A), ord_premise(B,P), conc(A,CA), contrary_only(CA,P).

defeat(A,B) :- arg(A), subarg(B,BP), top_kind(BP,defeasible),
               conc(A,CA), conc(BP,CB), conflict(CA,CB), not weaker(A,BP).

defeat(A,B) :- arg(A), subarg(B,BP), observation_based(BP),
               conc(BP,P), ord_premise(B,P),
               conc(A,CA), conflict(CA,P), not weaker(A,BP).

#show raw_attack/3.
#show defeat/2.
