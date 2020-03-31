#!python
from json import dumps
from ansible.errors import AnsibleError, AnsibleFilterError
from ansible.template import recursive_check_defined
from ansible.module_utils.common._collections_compat import MutableMapping, MutableSequence
from ansible.module_utils._text import to_native, to_text
from ansible.module_utils.six import iteritems, string_types
from ansible.module_utils.common.collections import is_sequence

def _validate_mutable_mappings(a, b):
    """
    Internal convenience function to ensure arguments are MutableMappings

    This checks that all arguments are MutableMappings or raises an error

    :raises AnsibleError: if one of the arguments is not a MutableMapping
    """

    # If this becomes generally needed, change the signature to operate on
    # a variable number of arguments instead.

    if not (isinstance(a, MutableMapping) and isinstance(b, MutableMapping)):
        myvars = []
        for x in [a, b]:
            try:
                myvars.append(dumps(x))
            except Exception:
                myvars.append(to_native(x))
        raise AnsibleError("failed to combine variables, expected dicts but got a '{0}' and a '{1}': \n{2}\n{3}".format(
            a.__class__.__name__, b.__class__.__name__, myvars[0], myvars[1])
        )

def merge_hash(x, y, recursive=True, list_merge='replace'):
    """
    Return a new dictionary result of the merges of y into x,
    so that keys from y take precedence over keys from x.
    (x and y aren't modified)
    """
    if list_merge not in ('replace', 'keep', 'append', 'prepend', 'append_rp', 'prepend_rp'):
        raise AnsibleError("merge_hash: 'list_merge' argument can only be equal to 'replace', 'keep', 'append', 'prepend', 'append_rp' or 'prepend_rp'")

    # verify x & y are dicts
    _validate_mutable_mappings(x, y)

    # to speed things up: if x is empty or equal to y, return y
    # (this `if` can be remove without impact on the function
    #  except performance)
    if x == {} or x == y:
        return y.copy()

    # in the following we will copy elements from y to x, but
    # we don't want to modify x, so we create a copy of it
    x = x.copy()

    # to speed things up: use dict.update if possible
    # (this `if` can be remove without impact on the function
    #  except performance)
    if not recursive and list_merge == 'replace':
        x.update(y)
        return x

    # insert each element of y in x, overriding the one in x
    # (as y has higher priority)
    # we copy elements from y to x instead of x to y because
    # there is a high probability x will be the "default" dict the user
    # want to "patch" with y
    # therefore x will have much more elements than y
    for key, y_value in iteritems(y):
        # if `key` isn't in x
        # update x and move on to the next element of y
        if key not in x:
            x[key] = y_value
            continue
        # from this point we know `key` is in x

        x_value = x[key]

        # if both x's element and y's element are dicts
        # recursively "combine" them or override x's with y's element
        # depending on the `recursive` argument
        # and move on to the next element of y
        if isinstance(x_value, MutableMapping) and isinstance(y_value, MutableMapping):
            if recursive:
                x[key] = merge_hash(x_value, y_value, recursive, list_merge)
            else:
                x[key] = y_value
            continue

        # if both x's element and y's element are lists
        # "merge" them depending on the `list_merge` argument
        # and move on to the next element of y
        if isinstance(x_value, MutableSequence) and isinstance(y_value, MutableSequence):
            if list_merge == 'replace':
                # replace x value by y's one as it has higher priority
                x[key] = y_value
            elif list_merge == 'append':
                x[key] = x_value + y_value
            elif list_merge == 'prepend':
                x[key] = y_value + x_value
            elif list_merge == 'append_rp':
                # append all elements from y_value (high prio) to x_value (low prio)
                # and remove x_value elements that are also in y_value
                # we don't remove elements from x_value nor y_value that were already in double
                # (we assume that there is a reason if there where such double elements)
                # _rp stands for "remove present"
                x[key] = [z for z in x_value if z not in y_value] + y_value
            elif list_merge == 'prepend_rp':
                # same as 'append_rp' but y_value elements are prepend
                x[key] = y_value + [z for z in x_value if z not in y_value]
            # else 'keep'
            #   keep x value even if y it's of higher priority
            #   it's done by not changing x[key]
            continue

        # else just override x's element with y's one
        x[key] = y_value

    return x

def flatten(mylist, levels=None):

    ret = []
    for element in mylist:
        if element in (None, 'None', 'null'):
            # ignore undefined items
            break
        elif is_sequence(element):
            if levels is None:
                ret.extend(flatten(element))
            elif levels >= 1:
                # decrement as we go down the stack
                ret.extend(flatten(element, levels=(int(levels) - 1)))
            else:
                ret.append(element)
        else:
            ret.append(element)

    return ret

class FilterModule(object):
    def filters(self):
        return {'combine_devel': self.combine_devel}

    def combine_devel(self, *terms, **kwargs):
        '''Combine filter from devel branch'''

        recursive = kwargs.pop('recursive', False)
        list_merge = kwargs.pop('list_merge', 'replace')
        if kwargs:
            raise AnsibleFilterError("'recursive' and 'list_merge' are the only valid keyword arguments")

        # allow the user to do `[dict1, dict2, ...] | combine`
        dictionaries = flatten(terms, levels=1)

        # recursively check that every elements are defined (for jinja2)
        recursive_check_defined(dictionaries)

        if not dictionaries:
            return {}

        if len(dictionaries) == 1:
            return dictionaries[0]

        # merge all the dicts so that the dict at the end of the array have precedence
        # over the dict at the beginning.
        # we merge the dicts from the highest to the lowest priority because there is
        # a huge probability that the lowest priority dict will be the biggest in size
        # (as the low prio dict will hold the "default" values and the others will be "patches")
        # and merge_hash create a copy of it's first argument.
        # so high/right -> low/left is more efficient than low/left -> high/right
        high_to_low_prio_dict_iterator = reversed(dictionaries)
        result = next(high_to_low_prio_dict_iterator)
        for dictionary in high_to_low_prio_dict_iterator:
            result = merge_hash(dictionary, result, recursive, list_merge)

        return result
