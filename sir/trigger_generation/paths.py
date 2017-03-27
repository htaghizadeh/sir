# Copyright (c) Wieland Hoffmann
# License: MIT, see LICENSE for details
from sqlalchemy.orm import class_mapper
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.orm.interfaces import ONETOMANY, MANYTOONE
from sqlalchemy.orm.properties import ColumnProperty, RelationshipProperty
from sqlalchemy.orm.descriptor_props import CompositeProperty


class PathPart(object):
    """
    A class representing part of a selection along a path across tables. Its
    subclasses can be used to construct SELECT statements programmatically,
    knowing only the relationship between the tables.

    Calling :func:`~sir.trigger_generation.PathPart.render` on the outermost
    :class:`PathPart` in a chain will return a SELECT statement for the
    :attr:`pkname` attribute on the table :attr:`tablename` along the complete
    chain.

    >>> outer = ManyToOnePathPart("table_1", "id", "table_2_id")
    >>> inner = ColumnPathPart("table_2", "id")
    >>> outer.inner = inner
    >>> outer.render()
    'SELECT table_1.id FROM table_1 WHERE table_1.table_2_id IN ({new_or_old}.id)'

    For example, if the path is "areas.area" and the target table is
    "annotation", then the resulting SQL query will be the following:
    ```
    SELECT annotation.id
      FROM annotation
     WHERE annotation.id IN (
        SELECT area_annotation.area
          FROM area_annotation
         WHERE area_annotation.area IN ({new_or_old}.id)
    )
    ```

    If the path is just "area", then for the "annotation" table the resulting
    query will be the following:
    ```
    SELECT annotation.id
      FROM annotation
     WHERE annotation.id IN ({new_or_old}.annotation)
    ```
    """  # noqa
    def __init__(self, table_name, pk_name, inner=None):
        """
        :param str table_name: The name of the table.
        :param str pk_name: The primary key of the table.
        :param PathPart inner: Path that will be included in
        """
        self.table_name = table_name
        self.pk_name = pk_name
        self.inner = inner

    def render(self):
        """
        Render the selection represented by this object and its inner object
        into a string.

        :rtype: str
        """
        raise NotImplementedError


class OneToManyPathPart(PathPart):
    """
    A :class:`~sir.trigger_generation.PathPart` subclass used to represent a
    selection across a one-to-many relationship between two
    tables.
    """
    def render(self):
        return "SELECT {table}.{pk_name} FROM {table} WHERE {table}.{pk_name} IN ({inner})".format(
            pk_name=self.pk_name,
            table=self.table_name,
            inner=self.inner.render(),
        )


class ManyToOnePathPart(PathPart):
    """
    A :class:`~sir.trigger_generation.PathPart` subclass used to represent a
    selection across a many-to-one relationship between two
    tables.
    """
    def __init__(self, table_name, pk_name, fk_name, inner=None):
        PathPart.__init__(self, table_name, pk_name, inner)
        self.fk_name = fk_name

    def render(self):
        return "SELECT {table}.{pk_name} FROM {table} WHERE {table}.{fk_name} IN ({inner})".format(
            pk_name=self.pk_name,
            table=self.table_name,
            inner=self.inner.render(),
            fk_name=self.fk_name,
        )


class ColumnPathPart(PathPart):
    """
    A :class:`~sir.trigger_generation.PathPart` subclass used to represent the
    selection of the primary key column of the innermost SELECT statement in
    the chain.
    """
    def render(self):
        return "{{new_or_old}}.{pk_name}".format(pk_name=self.pk_name)


def unique_split_paths(paths):
    """
    For each path in ``paths``, yield each of its continuous subpaths.
    If a subpath appears in multiple paths, it will be yielded only once.

    :param [str] paths:
    :rtype: iterator over str
    """
    seen_paths = set()
    for path in paths:
        splits = path.split(".")
        split_length = len(splits)
        for i in xrange(1, split_length + 1):
            join = ".".join(splits[:i])
            if join not in seen_paths:
                seen_paths.add(join)
                yield join


def walk_path(model, path):
    """
    Walk ``path`` beginning at ``model`` and return the last model in the path.

    :param model: A :ref:`declarative <sqla:declarative_toplevel>` class.
    :param str path: The path itself.
    """
    # TODO(roman): Check if old comments in this function are still relevant
    current_model = model

    for i, path_elem in enumerate(path.split(".")):
        column = getattr(current_model, path_elem)

        # If this is not a column managed by SQLAlchemy, ignore it
        # TODO(roman): Document when this might happen
        if not isinstance(column, InstrumentedAttribute):
            # Let's assume some other path also covers this table
            return None

        prop = column.property  # Current property in the path

        if isinstance(prop, RelationshipProperty):
            current_model = prop.mapper.class_

        elif isinstance(prop, ColumnProperty) or isinstance(prop, CompositeProperty):
            # We're not interested in columns (or a collection or them) because
            # the relationship handling takes care of selections on primary keys
            # etc.
            return None

    return current_model