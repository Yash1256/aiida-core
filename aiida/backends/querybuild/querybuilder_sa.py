# -*- coding: utf-8 -*-

from datetime import datetime
try:
    import ultrajson as json
    from functools import partial
    # double_precision = 15, to replicate what PostgreSQL numerical type is

    #~ ../../backends/sqlalchemy/utils.py-    json_dumps = partial(json.dumps, double_precision=15)
    json_loads = partial(json.loads, precise_float=True)
except ImportError:
    from json import loads as json_loads
    #~ json_dumps = json.dumps



from aiida.backends.querybuild.querybuilder_base import AbstractQueryBuilder
from sa_init import (
        and_, or_, not_, except_, func as sa_func,
        aliased, Integer, Float, Boolean, JSONB, DateTime,
        jsonb_array_length, jsonb_typeof
    )

from sqlalchemy_utils.types.choice import Choice
from aiida.backends.sqlalchemy import session as sa_session
from aiida.backends.sqlalchemy.models.node import DbNode, DbLink, DbPath
from aiida.backends.sqlalchemy.models.computer import DbComputer
from aiida.backends.sqlalchemy.models.group import DbGroup, table_groups_nodes
from aiida.backends.sqlalchemy.models.user import DbUser

from aiida.common.exceptions import InputValidationError



class QueryBuilder(AbstractQueryBuilder):
    """
    QueryBuilder to use with SQLAlchemy-backend and
    schema defined in backends.sqlalchemy.models
    """

    def __init__(self, *args, **kwargs):
        from aiida.orm.implementation.sqlalchemy.node import Node as AiidaNode
        from aiida.orm.implementation.sqlalchemy.group import Group as AiidaGroup
        from aiida.orm.implementation.sqlalchemy.computer import Computer as AiidaComputer
        self.Link               = DbLink
        self.Path               = DbPath
        self.Node               = DbNode
        self.Computer           = DbComputer
        self.User               = DbUser
        self.Group              = DbGroup
        self.table_groups_nodes = table_groups_nodes
        self.AiidaNode          = AiidaNode
        self.AiidaGroup         = AiidaGroup
        self.AiidaComputer      = AiidaComputer
        super(QueryBuilder, self).__init__(*args, **kwargs)

    def _get_session(self):
        return sa_session

    @classmethod
    def _get_filter_expr_from_attributes(cls, operator, value, db_column, attr_key):

        def cast_according_to_type(path_in_json, value):
            if isinstance(value, bool):
                type_filter = jsonb_typeof(path_in_json)=='boolean'
                casted_entity = path_in_json.cast(Boolean)
            elif isinstance(value, (int, float)):
                type_filter = jsonb_typeof(path_in_json)=='number'
                casted_entity = path_in_json.cast(Float)
            elif isinstance(value, dict) or value is None:
                type_filter = jsonb_typeof(path_in_json)=='object'
                casted_entity = path_in_json.cast(JSONB) # BOOLEANS?
            elif isinstance(value, dict):
                type_filter = jsonb_typeof(path_in_json)=='array'
                casted_entity = path_in_json.cast(JSONB) # BOOLEANS?
            elif isinstance(value, str):
                type_filter = jsonb_typeof(path_in_json)=='string'
                casted_entity = path_in_json.astext
            elif value is None:
                type_filter = jsonb_typeof(path_in_json)=='null'
                casted_entity = path_in_json.cast(JSONB) # BOOLEANS?
            elif isinstance(value, datetime):
                # type filter here is filter whether this attributes stores
                # a string and a filter whether this string
                # is compatible with a datetime (using a regex)
                #  - What about historical values (BC, or before 1000AD)??
                #  - Different ways to represent the timezone

                type_filter = jsonb_typeof(path_in_json)=='string'
                regex_filter = path_in_json.astext.op(
                        "SIMILAR TO"
                    )("\d\d\d\d-[0-1]\d-[0-3]\dT[0-2]\d:[0-5]\d:\d\d\.\d+((\+|\-)\d\d:\d\d)?")
                type_filter =  and_(type_filter, regex_filter)
                casted_entity = path_in_json.cast(DateTime)
            else:
                raise Exception('Unknown type {}'.format(type(value)))
            return type_filter, casted_entity

        database_entity = db_column[tuple(attr_key)]
        if operator == '==':
            type_filter, casted_entity = cast_according_to_type(database_entity, value)
            expr = and_(type_filter, casted_entity == value)
        elif operator == '>':
            type_filter, casted_entity = cast_according_to_type(database_entity, value)
            expr = and_(type_filter, casted_entity > value)
        elif operator == '<':
            type_filter, casted_entity = cast_according_to_type(database_entity, value)
            expr = and_(type_filter, casted_entity < value)
        elif operator in ('>=', '=>'):
            type_filter, casted_entity = cast_according_to_type(database_entity, value)
            expr = and_(type_filter, casted_entity >= value)
        elif operator == ('<=', '=<'):
            type_filter, casted_entity = cast_according_to_type(database_entity, value)
            expr = and_(type_filter, casted_entity <= value)
        elif operator == 'of_type':
            # http://www.postgresql.org/docs/9.5/static/functions-json.html
            #  Possible types are object, array, string, number, boolean, and null.
            valid_types = ('object', 'array', 'string', 'number', 'boolean', 'null')
            if value not in valid_types:
                raise InputValidationError(
                    "value {} for of_type is not among valid types\n"
                    "{}".format(value, valid_types)
                )
            expr = jsonb_typeof(database_entity) == value
        elif operator == 'like':
            type_filter, casted_entity = cast_according_to_type(database_entity, value)
            expr = and_(type_filter, casted_entity.like(value))
        elif operator == 'ilike':
            type_filter, casted_entity = cast_according_to_type(database_entity, value)
            expr = and_(type_filter, casted_entity.ilike(value))
        elif operator == 'in':
            type_filter, casted_entity = cast_according_to_type(database_entity, value[0])
            expr = and_(type_filter, casted_entity.in_(value))
        elif operator == 'contains':
            expr = database_entity.cast(JSONB).contains(value)
        elif operator == 'has_key':
            expr = database_entity.cast(JSONB).has_key(value)
        elif operator == 'of_length':
            expr=  and_(
                jsonb_typeof(database_entity) == 'array',
                jsonb_array_length(database_entity.cast(JSONB)) == value
            )
        elif operator == 'longer':
            expr = and_(
                jsonb_typeof(database_entity) == 'array',
                jsonb_array_length(database_entity.cast(JSONB)) > value
            )
        elif operator == 'shorter':
            expr =  and_(
                jsonb_typeof(database_entity) == 'array',
                jsonb_array_length(database_entity.cast(JSONB)) < value
            )
        else:
            raise InputValidationError(
                "Unknown operator {} for filters in JSON field".format(operator)
            )
        return expr


    def _get_projectable_attribute(
            self, alias, column, attrpath,
            cast=None, **kwargs
        ):

        entity = column[(attrpath)]
        if cast is None:
            entity = entity
        elif cast=='f':
            entity = entity.cast(Float)
        elif cast=='i':
            entity = entity.cast(Integer)
        elif cast=='b':
            entity = entity.cast(Boolean)
        elif cast=='t':
            entity = entity.astext
        elif cast=='j':
            entity = entity.cast(JSONB)
        elif cast=='d':
            entity = entity.cast(DateTime)
        else:
            raise InputValidationError(
                "Unkown casting key {}".format(cast)
            )
        return entity




    def _get_aiida_res(self, key, res):
        """
        Some instance returned by ORM (django or SA) need to be converted
        to Aiida instances (eg nodes). Choice (sqlalchemy_utils)
        will return their value

        :param key: The key
        :param res: the result returned by the query

        :returns: an aiida-compatible instance
        """
        if isinstance(res, (self.Group, self.Node, self.Computer, self.User)):
            returnval = res.get_aiida_class()
        elif isinstance(res, Choice):
            returnval = res.value
        elif key.startswith('attributes') or key.startswith('extras'):
            try:
                returnval = json_loads(res)
            except (TypeError, ValueError):
                # TypeError when it is not in ' '
                # ValueError if it is already a casted string
                returnval = res
        else:
            returnval = res
        return returnval


    def order_by(self, order_by):
        """
        Set the entity to order by

        :param order_by:
            This is a list of items, where each item is a dictionary specifies
            what to sort for an entity

        In each dictionary in that list,
        keys represent valid labels of entities (tables),
        values are list of columns
        """

        self._order_by = []

        if not isinstance(order_by, (list, tuple)):
            order_by = [order_by]


        for order_spec in order_by:
            if not isinstance(order_spec, dict):
                    raise InputValidationError(
                        "Invalid input for order_by statement: {}\n"
                        "I am expecting a dictionary ORMClass,"
                        "[columns to sort]"
                        "".format(order_spec)
                    )
            _order_spec = {}
            for key,items_to_order_by in order_spec.items():
                if not isinstance(items_to_order_by, (tuple, list)):
                    items_to_order_by = [items_to_order_by]
                label = self._get_label_from_specification(key)
                _order_spec[label] = []
                for item_to_order_by in items_to_order_by:
                    if isinstance(item_to_order_by, basestring):
                        item_to_order_by = {item_to_order_by:{}}
                    elif isinstance(item_to_order_by, dict):
                        pass
                    else:
                        raise InputValidationError(
                            "Cannot deal with input to order_by {}\n"
                            "of type{}"
                            "\n".format(item_to_order_by, type(item_to_order_by))
                        )
                    for k,v in item_to_order_by.items():
                        if isinstance(v, basestring):
                            item_to_order_by[k] = {'dtype':v}
                    _order_spec[label].append(item_to_order_by)

            self._order_by.append(_order_spec)
        return self
