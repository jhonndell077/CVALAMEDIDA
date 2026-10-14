import json
import unittest
import app
import onboarding
from drive_bank import clean_facts


class StructuredOnboardingTests(unittest.TestCase):
    def test_records_and_nested_functions_stay_separate_in_saved_files(self):
        payload = {
            'phones': ['809-555-0101', '809-555-0102'],
            'skills': ['Atención al cliente', 'Excel'],
            'education': [{'title': 'Bachiller', 'institution': 'Escuela A'}, {'title': 'Técnico', 'institution': 'Escuela B'}],
            'courses': [{'title': 'Curso A'}, {'title': 'Curso B'}],
            'experiences': [
                {'title': 'Camarero', 'employer': 'Restaurante A', 'responsibilities': ['Atender clientes', 'Tomar pedidos']},
                {'title': 'Parrillero', 'employer': 'Restaurante B', 'responsibilities': ['Cocinar carnes']}],
            'projects': [{'title': 'Aplicación', 'description': 'Mi aplicación web', 'technologies': ['Python', 'JavaScript']}],
            'references': [{'name': 'Persona A', 'role': 'Supervisora', 'phone': '809-555-0103'}, {'name': 'Persona B', 'role': 'Compañero', 'phone': '809-555-0104'}],
        }
        facts = {}
        for _, name, mime, raw in onboarding.collect(app, payload):
            self.assertTrue(name.endswith('.json'))
            self.assertEqual(mime, 'application/json')
            content = json.loads(raw)
            cleaned = clean_facts(content)
            for key in payload:
                if key in content: facts[key] = cleaned[key]
            if 'candidate' in content: facts['phones'] = cleaned['candidate']['phones']
        self.assertEqual(facts['phones'], payload['phones'])
        self.assertEqual(facts['skills'], payload['skills'])
        for section in ('education', 'courses', 'experiences', 'references'):
            self.assertEqual(len(facts[section]), 2)
        self.assertEqual(facts['experiences'][0]['responsibilities'], ['Atender clientes', 'Tomar pedidos'])
        self.assertEqual(facts['experiences'][1]['responsibilities'], ['Cocinar carnes'])
        self.assertEqual(facts['projects'][0]['technologies'], ['Python', 'JavaScript'])

    def test_empty_sections_are_optional_and_partial_records_are_rejected(self):
        self.assertEqual(onboarding.collect(app, {key: [] for key in [*onboarding.FIELDS, 'phones', 'skills']}), [])
        for payload in [
            {'references': [{'name': 'Persona'}]}, {'education': [{'institution': 'Escuela'}]},
            {'skills': ['Uno\nDos']}, {'experiences': [{'title': 'Chef', 'responsibilities': 'Uno\nDos'}]},
            {'phones': ['1'] * 11}, {'courses': [{'title': 'Curso'}] * 41},
        ]:
            with self.subTest(payload=payload), self.assertRaises(app.AppError):
                onboarding.collect(app, payload)

    def test_new_information_accepts_separate_functions_and_tools(self):
        _, record = app.new_information_record({'type': 'experiences', 'request_id': 'c' * 32, 'fields': {
            'title': 'Camarero', 'employer': 'Restaurante', 'category': 'Servicio', 'responsibilities': ['Atender clientes', 'Tomar pedidos']}})
        self.assertEqual([item['text'] for item in record['responsibilities']], ['Atender clientes', 'Tomar pedidos'])
        _, record = app.new_information_record({'type': 'projects', 'request_id': 'd' * 32, 'fields': {
            'title': 'Aplicación', 'description': 'Mi proyecto', 'technologies': ['Python', 'JavaScript']}})
        self.assertEqual(record['technologies'], ['Python', 'JavaScript'])
