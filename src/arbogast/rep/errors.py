"""Errors raised by exact finite-group representation operations."""


class RepresentationError(ValueError):
    """Base class for an invalid or unsupported representation operation."""


class InvalidActionError(RepresentationError):
    """The supplied matrices do not define an action of the concrete group."""


class ConcreteEmbeddingError(RepresentationError):
    """An operation attempted an implicit change of concrete group embedding."""


class NonSemisimpleError(RepresentationError):
    """An operation requires semisimplicity that has not been established."""


class NonSplitRepresentationError(RepresentationError):
    """A requested weight decomposition does not split over the base field."""
