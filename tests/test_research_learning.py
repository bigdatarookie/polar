"""Invented temporal-leakage and fixed-kernel correspondence controls."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import copy
import unittest
from polar.research_learning import feature_row, training_rows, fit_ridge, score_ridge, quantized_prediction


class ChronologicalRidge(unittest.TestCase):
    def market(self):
        days = [(date(2018,1,1)+timedelta(days=i)).isoformat() for i in range(400)]
        return {'dates': days, 'symbols': ['AAA', 'BBB'], 'dataset_revision': 'invented',
                'manifest_ref': {'sha256': 'a'*64, 'bytes': 1},
                'prices_micro': {d:{s:10000000+10000*i+(i%7)*1000*(j+1)
                                     for j,s in enumerate(['AAA','BBB'])} for i,d in enumerate(days)}}

    def cycles(self,m):
        return [{'signal':m['dates'][i], 'signal_index':i, 'entry':m['dates'][i+1],
                 'label_exit':m['dates'][i+22]} for i in [252,274]]

    def test_feature_prefix_invariance_and_future_label_rejection(self):
        m=self.market(); before=feature_row(m,'AAA',252)
        altered=copy.deepcopy(m)
        for day in m['dates'][253:]:altered['prices_micro'][day]['AAA']=999999999999
        self.assertEqual(feature_row(altered,'AAA',252),before)
        early=datetime.fromisoformat(m['dates'][260]+'T00:00:30+00:00')
        with self.assertRaisesRegex(ValueError,'RIDGE_LABEL_NOT_MATURE'):
            training_rows(m,self.cycles(m),early,timezone.utc)

    def test_existing_kernel_one_fit_and_frozen_scaler(self):
        m=self.market(); fit=datetime.fromisoformat(m['dates'][310]+'T00:00:30+00:00')
        fitted=fit_ridge(m,self.cycles(m),fit,timezone.utc)
        self.assertEqual(fitted['fit_calls'],1)
        self.assertEqual((fitted['model']['lambda'],fitted['model']['sum_loss_alpha']),(1,4))
        snapshot=copy.deepcopy(fitted)
        decision=datetime.fromisoformat(m['dates'][352]+'T00:01:00+00:00')
        scored=score_ridge(m,fitted,m['dates'][350],decision,timezone.utc)
        self.assertEqual(len(scored['scores']),2)
        self.assertEqual(fitted,snapshot)
        with self.assertRaisesRegex(ValueError,'RIDGE_SCORING_CHRONOLOGY'):
            score_ridge(m,fitted,m['dates'][350],fit-timedelta(seconds=1),timezone.utc)

    def test_prospective_quantizer_ties_and_finiteness(self):
        self.assertEqual(quantized_prediction(0.0000000000005), Decimal('0.000000000000'))
        self.assertEqual(quantized_prediction(0.0000000000015), Decimal('0.000000000002'))
        with self.assertRaises(ValueError):quantized_prediction(float('nan'))
