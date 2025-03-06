import xmlschema
from xml.etree.ElementTree import Element
from xml.etree.ElementTree import register_namespace as etree_register_namespace
from lxml.etree import Element as lxml_etree_element
from lxml.etree import register_namespace as lxml_etree_register_namespace
from xmlschema.exceptions import XMLSchemaTypeError, XMLSchemaValueError
from collections import namedtuple

ElementData = namedtuple('ElementData', ['tag', 'text', 'content', 'attributes'])

class CMLCuemsConverter(xmlschema.XMLSchemaConverter):

    def __init__(self, namespaces=None, dict_class=None, list_class=None,
                 etree_element_class=None, text_key='&', attr_prefix='',
                 cdata_prefix=None, indent=4, strip_namespaces=True,
                 preserve_root=False, force_dict=False, force_list=False, **kwargs):

        if etree_element_class is None or etree_element_class is Element:
            register_namespace = etree_register_namespace
        elif etree_element_class is lxml_etree_element:
            register_namespace = lxml_etree_register_namespace
        else:
            raise XMLSchemaTypeError("unsupported element class {!r}".format(etree_element_class))

        super(CMLCuemsConverter, self).__init__(namespaces=None, register_namespace=register_namespace, strip_namespaces=strip_namespaces)

        self.dict = dict_class or dict
        self.list = list_class or list
        self.etree_element_class = etree_element_class or Element
        self.text_key = text_key
        self.attr_prefix = attr_prefix
        self.cdata_prefix = cdata_prefix
        self.indent = indent
        self.preserve_root = preserve_root
        self.force_dict = force_dict
        self.force_list = force_list
 
      
    def element_decode(self, data, xsd_element, xsd_type=None, level=0):
        """
        Converts a decoded element data to a data structure.
        :param data: ElementData instance decoded from an Element node.
        :param xsd_element: the `XsdElement` associated to decoded the data.
        :param xsd_type: optional `XsdType` for supporting dynamic type through \
        xsi:type or xs:alternative.
        :param level: the level related to the decoding process (0 means the root).
        :return: a data structure containing the decoded data.
        """
        xsd_type = xsd_type or xsd_element.type
        result_dict = self.dict()
        if level == 0 and xsd_element.is_global() and not self.strip_namespaces and self:
            schema_namespaces = set(xsd_element.namespaces.values())
            result_dict.update(
                ('%s:%s' % (self.ns_prefix, k) if k else self.ns_prefix, v)
                for k, v in self._namespaces.items()
                if v in schema_namespaces
            )

        if xsd_type.is_simple() or xsd_type.has_simple_content():
            if data.attributes or self.force_dict and not xsd_type.is_simple():
                result_dict.update(t for t in self.map_attributes(data.attributes))
                if data.text is not None and data.text != '':
                    result_dict[self.text_key] = data.text
                return result_dict
            else:
                return data.text if data.text != '' else None
        else:
            if data.attributes:
                result_dict.update(t for t in self.map_attributes(data.attributes))

#            has_single_group = xsd_type.content_type.is_single()
            list_types = list if self.list is list else (self.list, list)
            dict_types = dict if self.dict is dict else (self.dict, dict)
            if data.content:
                for name, value, xsd_child in self.map_content(data.content):
                    try:
                        if isinstance(result_dict, list_types):
                            result = result_dict
                        else:
                            result = result_dict[name]
                    except KeyError:
                        if xsd_child is not None and not xsd_child.is_single():
                            result_dict = [{name:value}]
                        else:
                            result_dict[name] = self.list([value]) if self.force_list else value
                    else:
                        if isinstance(result, dict_types):
                            result_dict[name] = self.list([result, value])
                        elif isinstance(result, list_types) or not result:
                            result_dict.append({name:value})
                        else:
                            result.append(value)
                  

            elif data.text is not None and data.text != '':
                result_dict[self.text_key] = data.text

            if level == 0 and self.preserve_root:
                return self.dict(
                    [(self.map_qname(data.tag), result_dict if result_dict else None)]
                )
            return result_dict if result_dict else None

    def element_encode(self, obj, xsd_element, level=0):
        """
        Extracts XML decoded data from a data structure for encoding into an ElementTree.
        :param obj: the decoded object.
        :param xsd_element: the `XsdElement` associated to the decoded data structure.
        :param level: the level related to the encoding process (0 means the root).
        :return: an ElementData instance.
        """
        if level != 0:
            tag = xsd_element.name
        elif not self.preserve_root:
            tag = xsd_element.qualified_name
        else:
            tag = xsd_element.qualified_name
            try:
                obj = obj.get(tag, xsd_element.local_name)
            except (KeyError, AttributeError, TypeError):
                pass

        if not isinstance(obj, (self.dict, dict)):
            if xsd_element.type.is_simple() or xsd_element.type.has_simple_content():
                return ElementData(tag, obj, None, {})
            elif xsd_element.type.mixed and not isinstance(obj, list):
                return ElementData(tag, obj, None, {})
            else:
                return ElementData(tag, None, obj, {})

        text = None
        content = []
        attributes = {}

        for name, value in obj.items():
            if name == self.text_key and self.text_key:
                text = obj[self.text_key]
            elif (self.cdata_prefix and name.startswith(self.cdata_prefix)) or \
                    name[0].isdigit() and self.cdata_prefix == '':
                index = int(name[len(self.cdata_prefix):])
                content.append((index, value))
            elif name == self.ns_prefix:
                self[''] = value
            elif name.startswith('%s:' % self.ns_prefix):
                if not self.strip_namespaces:
                    self[name[len(self.ns_prefix) + 1:]] = value
            elif self.attr_prefix and name.startswith(self.attr_prefix):
                attr_name = name[len(self.attr_prefix):]
                ns_name = self.unmap_qname(attr_name, xsd_element.attributes)
                attributes[ns_name] = value
            elif not isinstance(value, (self.list, list)) or not value:
                content.append((self.unmap_qname(name), value))
            elif isinstance(value[0], (self.dict, dict, self.list, list)):
                ns_name = self.unmap_qname(name)
                content.extend((ns_name, item) for item in value)
            else:
                ns_name = self.unmap_qname(name)
                for xsd_child in xsd_element.type.content_type.iter_elements():
                    matched_element = xsd_child.match(ns_name, resolve=True)
                    if matched_element is not None:
                        if matched_element.type.is_list():
                            content.append((ns_name, value))
                        else:
                            content.extend((ns_name, item) for item in value)
                        break
                else:
                    if self.attr_prefix == '' and ns_name not in attributes:
                        for key, xsd_attribute in xsd_element.attributes.items():
                            if xsd_attribute.is_matching(ns_name):
                                attributes[key] = value
                                break
                        else:
                            content.append((ns_name, value))
                    else:
                        content.append((ns_name, value))

        return ElementData(tag, text, content, attributes)
