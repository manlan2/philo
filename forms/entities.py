from django.forms.models import ModelFormMetaclass, ModelForm
from django.utils.datastructures import SortedDict
from philo.utils import fattr


__all__ = ('EntityForm',)


def proxy_fields_for_entity_model(entity_model, fields=None, exclude=None, widgets=None, formfield_callback=lambda f, **kwargs: f.formfield(**kwargs)):
	field_list = []
	ignored = []
	opts = entity_model._entity_meta
	for f in opts.proxy_fields:
		if not f.editable:
			continue
		if fields and not f.name in fields:
			continue
		if exclude and f.name in exclude:
			continue
		if widgets and f.name in widgets:
			kwargs = {'widget': widgets[f.name]}
		else:
			kwargs = {}
		formfield = formfield_callback(f, **kwargs)
		if formfield:
			field_list.append((f.name, formfield))
		else:
			ignored.append(f.name)
	field_dict = SortedDict(field_list)
	if fields:
		field_dict = SortedDict(
			[(f, field_dict.get(f)) for f in fields
				if ((not exclude) or (exclude and f not in exclude)) and (f not in ignored) and (f in field_dict)]
		)
	return field_dict


# BEGIN HACK - This will not be required after http://code.djangoproject.com/ticket/14082 has been resolved

class EntityFormBase(ModelForm):
	pass

_old_metaclass_new = ModelFormMetaclass.__new__

def _new_metaclass_new(cls, name, bases, attrs):
	formfield_callback = attrs.get('formfield_callback', None)
	if formfield_callback is None:
		formfield_callback = lambda f, **kwargs: f.formfield(**kwargs)
	new_class = _old_metaclass_new(cls, name, bases, attrs)
	opts = new_class._meta
	if issubclass(new_class, EntityFormBase) and opts.model:
		# "override" proxy fields with declared fields by excluding them if there's a name conflict.
		exclude = (list(opts.exclude or []) + new_class.declared_fields.keys()) or None
		proxy_fields = proxy_fields_for_entity_model(opts.model, opts.fields, exclude, opts.widgets, formfield_callback) # don't pass in formfield_callback
		new_class.proxy_fields = proxy_fields
		new_class.base_fields.update(proxy_fields)
	return new_class

ModelFormMetaclass.__new__ = staticmethod(_new_metaclass_new)

# END HACK


class EntityForm(EntityFormBase): # Would inherit from ModelForm directly if it weren't for the above HACK
	def __init__(self, *args, **kwargs):
		initial = kwargs.pop('initial', None)
		instance = kwargs.get('instance', None)
		if instance is not None:
			new_initial = {}
			for f in instance._entity_meta.proxy_fields:
				if self._meta.fields and not f.name in self._meta.fields:
					continue
				if self._meta.exclude and f.name in self._meta.exclude:
					continue
				new_initial[f.name] = f.value_from_object(instance)
		else:
			new_initial = {}
		if initial is not None:
			new_initial.update(initial)
		kwargs['initial'] = new_initial
		super(EntityForm, self).__init__(*args, **kwargs)
	
	@fattr(alters_data=True)
	def save(self, commit=True):
		cleaned_data = self.cleaned_data
		instance = super(EntityForm, self).save(commit=False)
		
		for f in instance._entity_meta.proxy_fields:
			if not f.editable or not f.name in cleaned_data:
				continue
			if self._meta.fields and f.name not in self._meta.fields:
				continue
			if self._meta.exclude and f.name in self._meta.exclude:
				continue
			setattr(instance, f.attname, f.get_storage_value(cleaned_data[f.name]))
		
		if commit:
			instance.save()
			self.save_m2m()
		
		return instance