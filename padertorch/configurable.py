"""

Motivation of `Configurable` is to be able to serialize the configuration of
an entire pytorch_sanity module tree into a JSON.

You can instantiate a child of `Configurable` either with an `__init__`
resulting in an unparameterized module. If you instantiate it with
`from_config` you get a configured module.

If modules contain modules, look out for examples how to overwrite
`get_signature`. In most cases where you want to provide an instance as
a parameter to the `__init__` you can provide the parameters which were
used for that instance in your modified `get_signature`.

"""
import json
import inspect
import importlib

from pathlib import Path


class Configurable:
    """

    Example::

        from pytorch_sanity.configurable import Configurable
        class MyModule(Configurable):
            def __init__(self, a=1):
                pass
        MyModule.get_config()

    Results in::

        {'cls': 'MyModule', 'kwargs': {'a': 1}}

    """
    _config = None

    @property
    def config(self):
        if self._config is None:
            p_name = f'{Configurable.__module__}.{Configurable.__qualname__}'
            name = f'{self.__class__.__module__}.{self.__class__.__qualname__}'
            raise Exception(
                f'The config property of a {p_name} object\n'
                f'is only available, when the object is '
                f'produced from "from_config".\n'
                f'You tried to get it for an instance of {name}.'
            )
        return self._config

    @config.setter
    def config(self, value):
        if self._config is None:
            self._config = value
        else:
            p_name = f'{Configurable.__module__}.{Configurable.__qualname__}'
            name = f'{self.__class__.__module__}.{self.__class__.__qualname__}'
            raise Exception(
                f'The config property of a {p_name} object\n'
                f'can only be set once.\n'
                f'You tried to set it for an instance of {name}.'
            )

    @classmethod
    def get_signature(cls):
        """
        Checks signature of __init__. If parameters have defaults, return
        these in a dictionary.

        Returns:

        """

        sig = inspect.signature(cls)
        defaults = {}
        p: inspect.Parameter
        for name, p in sig.parameters.items():
            if p.default is not inspect.Parameter.empty:
                defaults[name] = p.default
        return defaults

    @classmethod
    def get_config(
            cls,
            updates=None,
            out_config=None,
    ):
        """
        Provides configuration to allow instantiation with
        module = Module.from_config(Module.get_config())

        Args:
            updates: dict with values to be modified w.r.t. defaults.
                Sub-configurations are updated accordingly if top-level-keys
                are changed. An Exception is raised if update_dict has unused
                entries.
            out_config: Provide an empty dict which is a Sacred config local
                variable. This allow Sacred to influence dependent parameters.

        Returns: Config

        """
        config = out_config

        if config is None:
            config = {
                'cls': class_to_str(cls)
            }
        elif 'cls' not in config:
            config['cls'] = class_to_str(cls)
        else:
            config['cls'] = class_to_str(config['cls'])

        # This assert is for sacred that may change values in the config dict.
        if inspect.isclass(import_class(config['cls'])) \
                and issubclass(import_class(config['cls']), Configurable):
            # When subclass of Configurable expect proper subclass
            assert issubclass(import_class(config['cls']), cls), (
                config['cls'], cls
            )

        if hasattr(import_class(config['cls']), 'get_signature'):
            defaults = import_class(config['cls']).get_signature()
        else:
            defaults = Configurable.get_signature.__func__(
                import_class(config['cls'])
            )

        config['kwargs'] = {
            **recursive_class_to_str(defaults),
            **config.get('kwargs', {}),
            **config.get(config['cls'], {}),
        }

        for key in list(config.keys()):
            if key not in ['cls', 'kwargs']:
                del config[key]

        if updates is None:
            updates = dict()

        try:
            update_config(config['kwargs'], updates)
        except ConfigUpdateException as e:
            raise Exception(
                f'{cls.__module__}.{cls.__qualname__}: '
                f'Updates that are not used anywhere: {e}'
            )

        # Test if the kwargs are valid
        sig = inspect.signature(import_class(config['cls']))

        # Remove default -> force completely described
        sig = sig.replace(
            parameters=[p.replace(
                default=inspect.Parameter.empty
            ) for p in sig.parameters.values()]
        )
        try:
            bound_arguments: inspect.BoundArguments = sig.bind(
                **config['kwargs']
            )
            bound_arguments.apply_defaults()
        except TypeError as e:
            unexpected_keyword = 'got an unexpected keyword argument '
            if unexpected_keyword in str(e):
                func_name, keyword = str(e).split(unexpected_keyword)
                keyword = keyword.strip().strip("'")
                available_keys = sig.parameters.keys()

                import difflib
                suggestions = difflib.get_close_matches(
                    keyword, available_keys,
                )

                # CB: Is it better to print with assigned values or without?
                sig_wo_anno = sig.replace(
                    parameters=[p.replace(
                        annotation=inspect.Parameter.empty,
                        default=config['kwargs'].get(
                            p.name, inspect.Parameter.empty
                        ),
                    ) for p in sig.parameters.values()]
                )
                raise TypeError(
                    f'{config["cls"]} {e}\n'
                    f'Did you mean one of these {suggestions}?\n'
                    f'Call signature: {sig_wo_anno}\n'
                    f'Where\n'
                    f'     kwargs.keys(): {config["kwargs"].keys()}\n'
                    f'     error msg: {e}'
                ) from e
            else:
                raise TypeError(
                    f'The test, if the call {config["cls"]}(**kwargs) would '
                    f'be successful, failed.\n'
                    f'Where\n'
                    f'     kwargs: {config["kwargs"]}\n'
                    f'     signature: {sig}\n'
                    f'     updates: {updates}\n'
                    f'     error msg: {e}'
                ) from e

        # Guarantee that config is json serializable
        try:
            _ = json.dumps(config)
        except TypeError as e:
            from IPython.lib.pretty import pprint
            print('#' * 20, 'JSON Failure config', '#' * 20)
            pprint(config)
            print('#' * 60)
            raise

        return config

    @classmethod
    def from_config(
            cls,
            config,
    ) -> 'Configurable':
        # assert do not use defaults
        assert 'cls' in config, (cls, config)
        assert issubclass(import_class(config['cls']), cls), (config['cls'], cls)
        new = config_to_instance(config)
        # new.config = config
        return new


def import_class(name: str):
    if not isinstance(name, str):
        return name
    splitted = name.split('.')
    module_name = '.'.join(splitted[:-1])
    if module_name == '':
        module_name = '__main__'
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError:
        print(
            f'Tried to import module {module_name} to import class '
            f'{splitted[-1]}. During import an error happened. '
            f'Make sure that\n'
            f'\t1. This is the class you want to import.\n'
            f'\t2. You activated the right environment.\n'
            f'\t3. The module exists and has been installed with pip.\n'
            f'\t4. You can import the module (and class) in ipython.\n'
        )
        raise
    try:
        return getattr(module, splitted[-1])
    except AttributeError as e:
        raise AttributeError(
            f'Module {module} has no attribute {splitted[-1]}.'
        )


def class_to_str(cls):
    """
    >>> import padertorch
    >>> class_to_str(padertorch.Model)
    'pytorch_sanity.base.Model'
    >>> class_to_str('pytorch_sanity.Model')
    'pytorch_sanity.base.Model'
    """
    if isinstance(cls, str):
        cls = import_class(cls)
    module = cls.__module__
    if module != '__main__':
        return f'{module}.{cls.__qualname__}'
    else:
        return f'{cls.__qualname__}'


def recursive_class_to_str(dictionary):
    """
    changes Configurable Objects to import path string
    changes Path to str
    >>> from padertorch import Model
    >>> recursive_class_to_str([{'cls': 'pytorch_sanity.Model'}])
    [{'cls': 'pytorch_sanity.base.Model'}]
    >>> recursive_class_to_str([{'cls': Model, Model: {}}])
    [{'cls': 'pytorch_sanity.base.Model', 'pytorch_sanity.base.Model': {}}]
    """
    if isinstance(dictionary, dict):
        if 'cls' in dictionary:
            return {
                class_to_str(k) if not isinstance(k, str) else k
                :
                class_to_str(v) if k == 'cls' else recursive_class_to_str(v)
                for k, v in dictionary.items()
            }
        else:
            return dictionary.__class__({
                k: recursive_class_to_str(v)
                for k, v in dictionary.items()
            })
    elif isinstance(dictionary, (tuple, list)):
        return dictionary.__class__([
            recursive_class_to_str(l)
            for l in dictionary
        ])
    elif isinstance(dictionary, Path):
        return str(dictionary)
    else:
        return dictionary


class ConfigUpdateException(Exception):
    pass


def update_config(config, updates):
    """

    :param config: config dict
    :param updates: updates dict.
    :return:
    """
    # ToDo: tuple and lists (e.g. Trainer models and optimizers)
    if 'cls' in config or 'cls' in updates:
        if 'cls' in updates:
            config['cls'] = class_to_str(updates['cls'])
        sub_updates = {
            **updates.get('kwargs', dict()),
            **updates.get(config['cls'], dict()),
        }

        cls = import_class(config['cls'])
        if hasattr(cls, 'get_config'):
            # inplace
            cls.get_config(
                updates=sub_updates,
                out_config=config,
            )
        else:
            Configurable.get_config.__func__(
                cls,
                updates=sub_updates,
                out_config=config,
            )
    else:
        for key in sorted(list(config.keys())):
            if isinstance(config[key], dict):
                update_config(
                    config[key],
                    updates.pop(key) if updates and key in updates else dict(),
                )
            elif updates and key in updates:
                new_value = updates.pop(key)
                if isinstance(new_value, dict):
                    config[key] = {}
                    update_config(
                        config[key],
                        new_value,
                    )
                else:
                    config[key] = new_value

        for key in list(updates.keys()):
            if isinstance(updates[key], dict):
                config[key] = {}
                update_config(
                    config[key],
                    updates.pop(key),
                )
            else:
                config[key] = updates.pop(key)


def config_to_instance(config):
    if isinstance(config, dict):
        if 'cls' in config:
            assert 'kwargs' in config, config
            assert len(config) == 2, (config.keys(), config)
            new = import_class(config['cls'])(
                **config_to_instance(config['kwargs'])
            )
            new.config = config
            return new
        else:
            return {k: config_to_instance(v) for k, v in config.items()}
    elif isinstance(config, (tuple, list)):
        return config.__class__([
            config_to_instance(l) for l in config
        ])
    else:
        return config