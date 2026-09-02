# A Programming Paradigm for Spatiotemporal Composability

**[Read the paper (PDF)](paper.pdf)** · Draft of August 13, 2026

> This is a preprint under active revision. The content may change substantially; please cite the latest version and check back before relying on specific results.

## Abstract

Modern software—from plugin systems to self-evolving agent harnesses—increasingly requires _dynamic composition_, yet its formal foundations remain underdeveloped. We identify two orthogonal dimensions of the problem: _temporal composability_, the ability to completely revert a component's side effects upon removal, and _spatial composability_, the ability to declare and reactively manage inter-component dependencies.
We address the two dimensions by lifting classical effect and coeffect concepts to runtime mechanisms.
In particular, we formalize _revertible effects_, in which every context transformation carries an inverse that the runtime tracks.
We formalize _reactive coeffects_, in which each change of the context notifies a component against its coeffect specification.
We unify the effect context and the coeffect context into a single _context type_, which constitutes a programming paradigm.
After that, we combine these mechanisms into the notion of a _component_ and give a calculus of dynamic composition, whose metatheory carries spatiotemporal composability from a single component to a whole system of interleaved components.
We implement these ideas in _Cordis_, a meta-framework of spatiotemporal composability that provides a core library with effect tracking and coeffect resolution, as well as a declarative component loader with configuration reconciliation and hot module replacement.

## Contact

Questions, comments, and corrections about the paper are welcome by email: [shigma@cordis.io](mailto:shigma@cordis.io).
