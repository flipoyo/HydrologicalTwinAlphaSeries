import json
from abc import ABCMeta, abstractmethod


class FactoryClass(metaclass=ABCMeta):
    @classmethod
    def fromDict(cls, a_dict):
        return cls(a_dict)

    @classmethod
    def fromJsonString(cls, a_json_string):
        try:
            a_dict = json.loads(a_json_string)
        except ValueError:
            print("not a valid JSON string", flush=True)
            return None
        return cls(a_dict)

    @classmethod
    def fromJsonFile(cls, a_filename):
        try:
            with open(a_filename, encoding="utf-8") as json_file:
                a_dict = json.load(json_file)

            for key in a_dict.keys():
                if isinstance(a_dict[key], dict):
                    try:
                        a_dict[key] = {
                            int(subkey): int(subvalue)
                            if isinstance(subvalue, str)
                            else subvalue
                            for subkey, subvalue in a_dict[key].items()
                        }
                    except Exception:
                        pass

                if isinstance(a_dict[key], dict):
                    try:
                        a_dict[key] = {
                            int(subkey): subvalue
                            if isinstance(subvalue, str)
                            else subvalue
                            for subkey, subvalue in a_dict[key].items()
                        }
                    except Exception:
                        pass

        except FileNotFoundError as exc:
            print(exc)
            raise exc
        except ValueError as exc:
            print(exc)
            raise exc
        return cls(a_dict)

    @abstractmethod
    def __init__(self, a_dict):
        return