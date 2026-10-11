"""Regressions from the owner's October 11 Mira conversations."""
from pathlib import Path
import unittest
from agent import parse_request
from buyer_memory import no_match_reply
from conversation_engine import conversational_turn
from conversation_memory import update_preferences
from mira_understanding import understand_request
from property_search import load_properties

class RecentChatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_properties()

    def test_actions_are_not_locations(self):
        for text in ('Im looking for a property to purchase', "i don't want to change any preferance", 'i would like to visit the property', 'i want to vist the VGN listing in person'):
            with self.subTest(text=text):
                self.assertEqual(parse_request(text,self.data).location,'')
                self.assertEqual(update_preferences(text,self.data,{'location':'Avadi'})['location'],'Avadi')
        self.assertEqual(parse_request('show property near Taramani',self.data).location.casefold(),'taramani')

    def test_purchase_is_intent_even_with_stale_state_or_bad_catalogue(self):
        import pandas as pd
        polluted = pd.DataFrame({'locality':['Purchase'], 'city':['Chennai']})
        for text in ('purchase', 'I want to purchase', 'purchase la'):
            self.assertEqual(parse_request(text, polluted).location, '')
        turn = conversational_turn('Im looking for a property to purchase', self.data, [], {'location':'Purchase', 'max_budget':4000000})
        self.assertEqual(turn['intent'], 'purchase_location_needed')
        self.assertNotIn('location', turn['context'])
        self.assertEqual(turn['context']['max_budget'],4000000)
        self.assertIn('Which city or area', turn['reply'])

    def test_correction_preserves_budget_and_reset_clears_all(self):
        context={'location':'Purchase','max_budget':3000000}
        turn=conversational_turn('i did not mention the location',self.data,[],context)
        self.assertEqual(turn['intent'],'location_correction')
        self.assertEqual(turn['context'],{'max_budget':3000000})
        turn=conversational_turn('remove my previous preferance',self.data,[],context,{'selected':{'title':'Old home'},'excluded_terms':['Avadi']})
        self.assertEqual(turn['context'],{})
        self.assertNotIn('selected',turn['memory'])
        self.assertNotIn('excluded_terms',turn['memory'])
        self.assertIn('removed_suggestions',turn)

    def test_auction_question_does_not_change_filters(self):
        context={'location':'Madurai','max_budget':4000000,'listing_statuses':['Existing sale','Project reference']}
        turn=conversational_turn('why is there auction symbol in the suggestion',self.data,[],context)
        self.assertEqual(turn['intent'],'auction_explanation')
        self.assertEqual(turn['context'],context)
        self.assertIn('bidding',turn['reply'])

    def test_keep_preferences_and_budget_range(self):
        context={'location':'Madurai','max_budget':4000000}
        turn=understand_request("i don't want to change any preferance, show the details with my preferance",self.data,[],context)
        self.assertIn('results',turn)
        self.assertEqual(turn['context']['location'],'Madurai')
        reply=no_match_reply(self.data,turn['memory']|{'requirements':context})
        self.assertIn('unchanged',reply)
        self.assertNotIn('Which preference',reply)
        turn=understand_request('15-40 lakhs',self.data,[],{'location':'Madurai'})
        self.assertIn('results',turn)
        self.assertEqual(turn['context']['min_budget'],1500000)
        self.assertEqual(turn['context']['max_budget'],4000000)

    def test_interest_typos_and_visit_open_request(self):
        selected={'property_id':'test','title':'VGN Crofton Gardens'}
        turn=conversational_turn('Im intrested to purchase',self.data,[],{'location':'Avadi'},{'selected':selected})
        self.assertEqual(turn['intent'],'purchase_assistance_offer')
        visit=conversational_turn('i would like to visit the property',self.data,[],turn['context'],turn['memory'])
        self.assertEqual(visit['open_visit'],selected)
        self.assertEqual(visit['context']['location'],'Avadi')
        self.assertIn('not a confirmed appointment',visit['reply'])
        self.assertNotIn('example.com',visit['reply'])

    def test_multiple_selected_properties_need_choice(self):
        records=[{'title':'First home'},{'title':'Second home'}]
        memory={'selected_properties':records,'selected':records[-1]}
        turn=conversational_turn('Can I visit the selected properties directly',self.data,[],memory=memory)
        self.assertEqual(turn['intent'],'visit_property_selection')
        self.assertNotIn('open_visit',turn)
        chat=[{'role':'assistant','mode':'results','records':records}]
        turn=conversational_turn('first',self.data,chat,memory=turn['memory'])
        self.assertEqual(turn['open_visit']['title'],'First home')

    def test_chat_opens_booking_dialog(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_file(str(Path(__file__).with_name('website_sandbox.py')),default_timeout=60).run()
        app.session_state['buyer_memory']={'selected':{'property_id':'test','title':'Test home'}}
        next(x for x in app.text_input if x.label=='Message Mira').set_value('i would like to visit the property')
        next(x for x in app.button if x.label=='Send').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['visit_property']['title'],'Test home')
        self.assertTrue(any(x.label=='Request visit' for x in app.button))

    def test_recap_and_search_use_saved_preferences(self):
        context={'location':'Avadi','max_budget':4000000,'listing_statuses':['Existing sale','Project reference']}
        turn=conversational_turn('what are my previous preferances',self.data,[],context)
        self.assertEqual(turn['intent'],'preference_recap')
        self.assertIn('Avadi',turn['reply'])
        self.assertIn('40 lakh',turn['reply'])
        for text in ('search with my existing budget','search with these now?'):
            turn=understand_request(text,self.data,[],context)
            self.assertIn('results',turn)
            self.assertEqual(turn['context'],context)
        self.assertEqual(update_preferences('do not remove my previous preferences',self.data,context),context)

    def test_regular_sale_changes_auction_filter_only(self):
        context={'location':'Madurai','max_budget':4000000,'status':'Auction','listing_statuses':['Auction']}
        context=update_preferences('looking for a regular sale in avadi',self.data,context)
        self.assertEqual(context['location'].casefold(),'avadi')
        self.assertEqual(context['listing_statuses'],['Existing sale','Project reference'])
        turn=understand_request('looking for a regular sale in avadi',self.data,[],context)
        self.assertIn('results',turn)
        self.assertFalse((turn['results']['listing_status']=='Auction').any())

if __name__=='__main__':
    unittest.main()
