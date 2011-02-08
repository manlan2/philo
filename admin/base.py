from django.conf import settings
from django.contrib import admin
from django.contrib.contenttypes import generic
from django.http import HttpResponse
from django.utils import simplejson as json
from django.utils.html import escape
from philo.models import Tag, Attribute
from philo.models.fields.entities import ForeignKeyAttribute, ManyToManyAttribute
from philo.admin.forms.attributes import AttributeForm, AttributeInlineFormSet
from philo.admin.widgets import TagFilteredSelectMultiple
from philo.forms.entities import EntityForm, proxy_fields_for_entity_model
from mptt.admin import MPTTModelAdmin


COLLAPSE_CLASSES = ('collapse', 'collapse-closed', 'closed',)


class AttributeInline(generic.GenericTabularInline):
	ct_field = 'entity_content_type'
	ct_fk_field = 'entity_object_id'
	model = Attribute
	extra = 1
	allow_add = True
	classes = COLLAPSE_CLASSES
	form = AttributeForm
	formset = AttributeInlineFormSet
	fields = ['key', 'value_content_type']
	if 'grappelli' in settings.INSTALLED_APPS:
		template = 'admin/philo/edit_inline/grappelli_tabular_attribute.html'
	else:
		template = 'admin/philo/edit_inline/tabular_attribute.html'


def hide_proxy_fields(cls, attname, proxy_field_set):
	val_set = set(getattr(cls, attname))
	if proxy_field_set & val_set:
		cls._hidden_attributes[attname] = list(val_set)
		setattr(cls, attname, list(val_set - proxy_field_set))


class EntityAdminMetaclass(admin.ModelAdmin.__metaclass__):
	def __new__(cls, name, bases, attrs):
		# HACK to bypass model validation for proxy fields by masking them as readonly fields
		new_class = super(EntityAdminMetaclass, cls).__new__(cls, name, bases, attrs)
		form = getattr(new_class, 'form', None)
		if form:
			opts = form._meta
			if issubclass(form, EntityForm) and opts.model:
				proxy_fields = proxy_fields_for_entity_model(opts.model).keys()
				
				# Store readonly fields iff they have been declared.
				if 'readonly_fields' in attrs or not hasattr(new_class, '_real_readonly_fields'):
					new_class._real_readonly_fields = new_class.readonly_fields
				
				readonly_fields = new_class.readonly_fields
				new_class.readonly_fields = list(set(readonly_fields) | set(proxy_fields))
				
				# Additional HACKS to handle raw_id_fields and other attributes that the admin
				# uses model._meta.get_field to validate.
				new_class._hidden_attributes = {}
				proxy_fields = set(proxy_fields)
				hide_proxy_fields(new_class, 'raw_id_fields', proxy_fields)
		#END HACK
		return new_class


class EntityAdmin(admin.ModelAdmin):
	__metaclass__ = EntityAdminMetaclass
	form = EntityForm
	inlines = [AttributeInline]
	save_on_top = True
	
	def __init__(self, *args, **kwargs):
		# HACK PART 2 restores the actual readonly fields etc. on __init__.
		if hasattr(self, '_real_readonly_fields'):
			self.readonly_fields = self.__class__._real_readonly_fields
		if hasattr(self, '_hidden_attributes'):
			for name, value in self._hidden_attributes.items():
				setattr(self, name, value)
		# END HACK
		super(EntityAdmin, self).__init__(*args, **kwargs)
	
	def formfield_for_dbfield(self, db_field, **kwargs):
		"""
		Override the default behavior to provide special formfields for EntityEntitys.
		Essentially clones the ForeignKey/ManyToManyField special behavior for the Attribute versions.
		"""
		if not db_field.choices and isinstance(db_field, (ForeignKeyAttribute, ManyToManyAttribute)):
			request = kwargs.pop("request", None)
			# Combine the field kwargs with any options for formfield_overrides.
			# Make sure the passed in **kwargs override anything in
			# formfield_overrides because **kwargs is more specific, and should
			# always win.
			if db_field.__class__ in self.formfield_overrides:
				kwargs = dict(self.formfield_overrides[db_field.__class__], **kwargs)
			
			# Get the correct formfield.
			if isinstance(db_field, ManyToManyAttribute):
				formfield = self.formfield_for_manytomanyattribute(db_field, request, **kwargs)
			elif isinstance(db_field, ForeignKeyAttribute):
				formfield = self.formfield_for_foreignkeyattribute(db_field, request, **kwargs)
			
			# For non-raw_id fields, wrap the widget with a wrapper that adds
			# extra HTML -- the "add other" interface -- to the end of the
			# rendered output. formfield can be None if it came from a
			# OneToOneField with parent_link=True or a M2M intermediary.
			# TODO: Implement this.
			#if formfield and db_field.name not in self.raw_id_fields:
			#	formfield.widget = admin.widgets.RelatedFieldWidgetWrapper(formfield.widget, db_field, self.admin_site)
			
			return formfield
		return super(EntityAdmin, self).formfield_for_dbfield(db_field, **kwargs)
	
	def formfield_for_foreignkeyattribute(self, db_field, request=None, **kwargs):
		"""Get a form field for a ForeignKeyAttribute field."""
		db = kwargs.get('using')
		if db_field.name in self.raw_id_fields:
			kwargs['widget'] = admin.widgets.ForeignKeyRawIdWidget(db_field, db)
		#TODO: Add support for radio fields
		#elif db_field.name in self.radio_fields:
		#	kwargs['widget'] = widgets.AdminRadioSelect(attrs={
		#		'class': get_ul_class(self.radio_fields[db_field.name]),
		#	})
		#	kwargs['empty_label'] = db_field.blank and _('None') or None
		
		return db_field.formfield(**kwargs)
	
	def formfield_for_manytomanyattribute(self, db_field, request=None, **kwargs):
		"""Get a form field for a ManyToManyAttribute field."""
		db = kwargs.get('using')
		
		if db_field.name in self.raw_id_fields:
			kwargs['widget'] = admin.widgets.ManyToManyRawIdWidget(db_field, using=db)
			kwargs['help_text'] = ''
		#TODO: Add support for filtered fields.
		#elif db_field.name in (list(self.filter_vertical) + list(self.filter_horizontal)):
		#	kwargs['widget'] = widgets.FilteredSelectMultiple(db_field.verbose_name, (db_field.name in self.filter_vertical))
		
		return db_field.formfield(**kwargs)


class TreeAdmin(MPTTModelAdmin):
	pass


class TreeEntityAdmin(EntityAdmin, TreeAdmin):
	pass


class TagAdmin(admin.ModelAdmin):
	list_display = ('name', 'slug')
	prepopulated_fields = {"slug": ("name",)}
	search_fields = ["name"]
	
	def response_add(self, request, obj, post_url_continue='../%s/'):
		# If it's an ajax request, return a json response containing the necessary information.
		if request.is_ajax():
			return HttpResponse(json.dumps({'pk': escape(obj._get_pk_val()), 'unicode': escape(obj)}))
		return super(TagAdmin, self).response_add(request, obj, post_url_continue)


class AddTagAdmin(admin.ModelAdmin):
	def formfield_for_manytomany(self, db_field, request=None, **kwargs):
		"""
		Get a form Field for a ManyToManyField.
		"""
		# If it uses an intermediary model that isn't auto created, don't show
		# a field in admin.
		if not db_field.rel.through._meta.auto_created:
			return None
		
		if db_field.rel.to == Tag and db_field.name in (list(self.filter_vertical) + list(self.filter_horizontal)):
			opts = Tag._meta
			if request.user.has_perm(opts.app_label + '.' + opts.get_add_permission()):
				kwargs['widget'] = TagFilteredSelectMultiple(db_field.verbose_name, (db_field.name in self.filter_vertical))
				return db_field.formfield(**kwargs)
		
		return super(AddTagAdmin, self).formfield_for_manytomany(db_field, request, **kwargs)


admin.site.register(Tag, TagAdmin)