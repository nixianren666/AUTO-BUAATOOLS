"""Permanent user-requested automatic-selection exclusions; manual actions stay separate."""
import unicodedata

def permanently_excluded(course):
    name=unicodedata.normalize('NFKC',str(course.get('courseName') or ''))
    normalized=''.join(c for c in name if c.isalnum())
    return '耕趣农场' in normalized
