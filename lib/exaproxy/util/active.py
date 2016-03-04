
class ActiveCache (object):
	__slots__ = ['data', 'slots']

	def __init__ (self, slots=10):
		self.data = {}
		self.slots = [{} for _ in range(slots)]

	def __len__ (self):
		return len(self.data)

	def __contains__ (self, key):
		return key in self.data

	def __nonzero__ (self):
		return bool(self.data)

	def __getitem__ (self, key):
		slot = self.data[key]
		current = self.slots[0]

		if slot is not current:
			value = slot.pop(key)
			current[key] = value
			self.data[key] = current

		return value

	def __setitem__ (self, key, value):
		current = self.slots[0]

		if key in self.data:
			slot = self.data[key]
			slot.pop(key)

		current[key] = value
		self.data[key] = current

	def iteritems (self):
		return self.data.iteritems()

	def itervalues (self):
		return self.data.iteritems()

	def get (self, key, default=None):
		if key not in self.data:
			return default

		current = self.slots[0]
		slot = self.data[key]

		if slot is not current:
			value = slot.pop(key)
			current[key] = value
			self.data[key] = current

		else:
			value = slot[key]

		return value

	def pop (self, key, default=None):
		if key in self.data:
			slot = self.data.pop(key)

		else:
			slot = None

		if slot:
			return slot.pop(key)

		return default

	def shift (self, count):
		expired = self.slots[-1]
		self.slots = [{}] + self.slots[:-1]

		for key in expired:
			self.data.pop(key)

		return expired


