import unittest
import app
from test_app import valid_analysis, supervisor_analysis

class ProfessionalSummaryTests(unittest.TestCase):
    def test_summary_describes_real_profile_not_target_job(self):
        analysis=valid_analysis()
        analysis['vacancy']['position']='Director internacional sin experiencia bancaria'
        analysis['matching']['selected_skills'] += ['idioma-inexistente']
        summary=app.make_draft(analysis)['summary']
        self.assertNotIn(analysis['vacancy']['position'], summary)
        self.assertNotIn('documentada',summary)
        self.assertNotIn('orientado',summary)
        self.assertIn('Profesional con experiencia como',summary)
        self.assertNotIn('idioma-inexistente',summary)

    def test_different_requirements_prioritize_different_bank_capabilities(self):
        analysis=supervisor_analysis()
        analysis['vacancy']['mandatory_requirements']=['Control de inventario y supervisión de personal de cocina']
        inventory=app.make_draft(analysis)['summary']
        analysis['vacancy']['mandatory_requirements']=['Control de costos y planificación de procesos']
        costs=app.make_draft(analysis)['summary']
        self.assertNotEqual(inventory,costs)
        self.assertIn('control de inventario',inventory)
        self.assertIn('control de costos',costs)
        self.assertLessEqual(len(costs.split()),95)

    def test_direct_evidence_precedes_transferable_skills(self):
        analysis=valid_analysis()
        analysis['matching']['selected_skills']=['inventario','recepcion-almacen','microsoft-office','atencion-cliente']
        analysis['matching']['items']=[{'type':'directo','skill_ids':['microsoft-office'],'experience_ids':[]}]
        summary=app.make_draft(analysis)['summary']
        self.assertIn('Microsoft Word, Excel',summary)
        self.assertLess(summary.index('Microsoft'),summary.index('inventario'))

    def test_activity_based_job_title_uses_natural_grammar(self):
        summary=app.make_draft(valid_analysis())['summary']
        self.assertIn('en recepción de mercancía y almacén',summary.casefold())
        self.assertNotIn('como Recepción',summary)

    def test_no_selected_skills_uses_real_functions_and_keeps_unknown_requirements_out(self):
        analysis=valid_analysis()
        analysis['matching']['selected_skills']=[]
        analysis['vacancy']['mandatory_requirements']=['Inglés avanzado, diez años de experiencia y reducción de costos del 50%']
        summary=app.make_draft(analysis)['summary']
        self.assertIn('Entre mis funciones:',summary)
        self.assertNotIn('50%',summary)
        self.assertNotIn('Inglés',summary)
        self.assertNotIn('diez años',summary)
