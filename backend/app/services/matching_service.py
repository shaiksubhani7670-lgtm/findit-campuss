import logging
from datetime import datetime, date, timedelta, timezone
from difflib import SequenceMatcher
from app import db
from app.models.lost_item import LostItem
from app.models.found_item import FoundItem
from app.models.match import Match
from app.models.notification import Notification
from app.models.question_answer import QuestionAnswer

logger = logging.getLogger(__name__)

class MatchingService:
    """
    AI-powered similarity matching engine for FindIt Campus.
    Matches lost and found reports of the identical category created within 60 days.
    """

    def run_matching(self, report_id, report_type):
        """
        Run the matching engine for a newly submitted report.
        """
        logger.info(f"Running AI matching engine for {report_type} report #{report_id}")
        
        if report_type == 'lost':
            self._match_lost_item(report_id)
        else:
            self._match_found_item(report_id)

    def _match_lost_item(self, lost_id):
        lost_item = LostItem.query.get(lost_id)
        if not lost_item or lost_item.status == 'Cancelled':
            return

        # Find candidate found items of the same category, status 'Searching', created within last 60 days
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=60)
        candidates = FoundItem.query.filter(
            FoundItem.category == lost_item.category,
            FoundItem.status == 'Searching',
            FoundItem.created_at >= cutoff_date
        ).all()

        for found_item in candidates:
            self._compute_and_save_match(lost_item, found_item)

    def _match_found_item(self, found_id):
        found_item = FoundItem.query.get(found_id)
        if not found_item or found_item.status == 'Cancelled':
            return

        # Find candidate lost items of the same category, status 'Searching', created within last 60 days
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=60)
        candidates = LostItem.query.filter(
            LostItem.category == found_item.category,
            LostItem.status == 'Searching',
            LostItem.created_at >= cutoff_date
        ).all()

        for lost_item in candidates:
            self._compute_and_save_match(lost_item, found_item)

    def _compute_and_save_match(self, lost, found):
        # Calculate scores
        # 1. Image similarity (40%)
        # In this lightweight deployment we use fallback image comparison.
        # If both have images, we check if they match (simulated feature matcher). 
        # For demo purposes, we do a basic match of metadata plus color, or direct 0.85 default if paths match.
        has_images = lost.image_path is not None and found.image_path is not None
        image_score = 0.0
        if has_images:
            # Simulated high-confidence image matching
            image_score = 0.85 if lost.color.lower() in found.description.lower() else 0.5
        
        # 2. Brand & Model (20%)
        lost_brand = (lost.additional_details.get('brand', '') if lost.additional_details else '').strip().lower()
        lost_model = (lost.additional_details.get('model', '') if lost.additional_details else '').strip().lower()
        found_brand = (found.additional_details.get('brand', '') if found.additional_details else '').strip().lower()
        found_model = (found.additional_details.get('model', '') if found.additional_details else '').strip().lower()
        
        brand_sim = self._str_sim(lost_brand, found_brand)
        model_sim = self._str_sim(lost_model, found_model)
        brand_score = (brand_sim + model_sim) / 2.0

        # 3. Description (15%)
        desc_score = self._str_sim(lost.description, found.description)

        # 4. Color (10%)
        color_score = 0.0
        lost_col = lost.color.strip().lower()
        found_col = found.color.strip().lower()
        if lost_col == found_col:
            color_score = 1.0
        elif lost_col in found_col or found_col in lost_col:
            color_score = 0.8
        else:
            # Color groups helper
            color_groups = {
                'blue': ['dark blue', 'navy', 'sky blue', 'light blue'],
                'black': ['grey', 'dark grey', 'charcoal'],
                'white': ['cream', 'silver', 'grey'],
                'red': ['maroon', 'pink', 'orange']
            }
            matched_group = False
            for group, colors in color_groups.items():
                if (lost_col == group or lost_col in colors) and (found_col == group or found_col in colors):
                    color_score = 0.7
                    matched_group = True
                    break
            if not matched_group:
                color_score = 0.0

        # 5. Location + Date + Time (10%)
        # Location
        loc_score = 1.0 if lost.location.lower() == found.location.lower() else 0.2
        # Date
        days_diff = abs((found.date - lost.date).days)
        date_score = 0.0
        if days_diff == 0: date_score = 1.0
        elif days_diff <= 1: date_score = 0.9
        elif days_diff <= 3: date_score = 0.7
        elif days_diff <= 7: date_score = 0.5
        elif days_diff <= 14: date_score = 0.3
        elif days_diff <= 30: date_score = 0.1
        
        # Time
        time_score = 0.5
        if lost.time and found.time:
            t1 = lost.time.hour * 60 + lost.time.minute
            t2 = found.time.hour * 60 + found.time.minute
            min_diff = abs(t1 - t2)
            if min_diff <= 60: time_score = 1.0
            elif min_diff <= 180: time_score = 0.7
            elif min_diff <= 360: time_score = 0.4
            else: time_score = 0.1
            
        location_score = (loc_score + date_score + time_score) / 3.0

        # 6. Question Answers (5%)
        lost_qas = QuestionAnswer.query.filter_by(report_type='lost', report_id=lost.report_id).all()
        found_qas = QuestionAnswer.query.filter_by(report_type='found', report_id=found.report_id).all()
        
        qa_score = 0.0
        if lost_qas and found_qas:
            match_qa = 0
            total_qa = 0
            for l_qa in lost_qas:
                # Find matching question in found QAs
                for f_qa in found_qas:
                    if l_qa.question.strip().lower() == f_qa.question.strip().lower():
                        total_qa += 1
                        l_ans = l_qa.answer.strip().lower()
                        f_ans = f_qa.answer.strip().lower()
                        if l_ans == f_ans or l_ans in f_ans or f_ans in l_ans:
                            match_qa += 1
                        else:
                            # use similarity for free text questions
                            sim = self._str_sim(l_ans, f_ans)
                            if sim >= 0.7:
                                match_qa += 1
                            else:
                                match_qa += sim
            qa_score = (match_qa / total_qa) if total_qa > 0 else 0.5
        else:
            qa_score = 0.5

        # Calculate weighted overall score
        # Normalization if no images are present
        if has_images:
            overall = (image_score * 40.0 + 
                       brand_score * 20.0 + 
                       desc_score * 15.0 + 
                       color_score * 10.0 + 
                       location_score * 10.0 + 
                       qa_score * 5.0)
        else:
            # Scale remaining 60% of weights to 100%
            remaining_sum = (brand_score * 20.0 + 
                             desc_score * 15.0 + 
                             color_score * 10.0 + 
                             location_score * 10.0 + 
                             qa_score * 5.0)
            overall = (remaining_sum / 60.0) * 100.0

        # Structured parameter check: if Category, Brand, Model, Color, and Location match perfectly, 
        # and date/time are extremely close, we boost the score to ensure high confidence match.
        if brand_score >= 0.95 and color_score >= 0.95 and loc_score >= 0.95 and date_score >= 0.9:
            # Perfect structured details match. Boost the score to ensure it crosses 95.0%
            overall = max(overall, 96.5)

        overall = round(overall, 1)

        # Check if match already exists
        existing_match = Match.query.filter_by(
            lost_report_id=lost.report_id,
            found_report_id=found.report_id
        ).first()

        if existing_match:
            # Update score if higher
            if overall > existing_match.overall_score:
                existing_match.image_score = round(image_score * 100, 1)
                existing_match.brand_score = round(brand_score * 100, 1)
                existing_match.description_score = round(desc_score * 100, 1)
                existing_match.color_score = round(color_score * 100, 1)
                existing_match.location_score = round(location_score * 100, 1)
                existing_match.question_score = round(qa_score * 100, 1)
                existing_match.overall_score = overall
                db.session.commit()
            return

        # Save match details
        new_match = Match(
            lost_report_id=lost.report_id,
            found_report_id=found.report_id,
            image_score=round(image_score * 100, 1),
            brand_score=round(brand_score * 100, 1),
            description_score=round(desc_score * 100, 1),
            color_score=round(color_score * 100, 1),
            location_score=round(location_score * 100, 1),
            question_score=round(qa_score * 100, 1),
            overall_score=overall
        )
        db.session.add(new_match)

        # Update status if matched high confidence (95% threshold)
        if overall >= 95.0:
            lost.status = 'Matched'
            found.status = 'Matched'

            # Notify ONLY the person who lost the item (User A).
            # They are the one who needs to act — go claim the found item.
            notif_msg = (
                f"Great news! Someone found an item matching your lost '{lost.item_name}'. "
                f"It was found at '{found.location}' on {found.date.strftime('%d %b %Y')}. "
                f"AI Match Confidence: {overall}%. "
                f"Go to Match Alerts to view full details and proceed to claim it."
            )
            notification = Notification(
                student_id=lost.student_id,
                title=f"🎉 Your Lost Item May Have Been Found! ({overall}% match)",
                message=notif_msg
            )
            db.session.add(notification)

        db.session.commit()

        # Send match email notification async (for >=70% matches)
        if overall >= 70.0:
            try:
                from app.models.student import Student
                from app.services.email_service import send_match_found_email
                student = Student.query.get(lost.student_id)
                if student:
                    send_match_found_email(student, lost, found, overall)
            except Exception as e:
                logger.warning(f"Failed to send match email: {e}")

        logger.info(f"Match stored: Lost#{lost.report_id} ↔ Found#{found.report_id} | Score: {overall}%")

    def _str_sim(self, s1, s2):
        """Hybrid similarity: sequence match + token set overlap."""
        if not s1 or not s2:
            return 0.5
        a, b = s1.lower().strip(), s2.lower().strip()
        # Sequence ratio
        seq_ratio = SequenceMatcher(None, a, b).ratio()
        # Token set overlap (Jaccard)
        tokens_a = set(a.split())
        tokens_b = set(b.split())
        # Remove common stop words that add noise
        stopwords = {'i', 'my', 'a', 'an', 'the', 'and', 'or', 'in', 'on', 'at', 'to',
                     'of', 'it', 'its', 'this', 'that', 'was', 'is', 'are', 'lost',
                     'found', 'near', 'by', 'with', 'have', 'has', 'had', 'some'}
        clean_a = tokens_a - stopwords
        clean_b = tokens_b - stopwords
        if clean_a and clean_b:
            intersection = clean_a & clean_b
            union = clean_a | clean_b
            jaccard = len(intersection) / len(union) if union else 0.0
        else:
            jaccard = seq_ratio
        # Weighted blend: 50% sequence + 50% token overlap
        return round((seq_ratio * 0.5 + jaccard * 0.5), 4)

matching_service = MatchingService()
