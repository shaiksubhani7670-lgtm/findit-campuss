import logging
from datetime import datetime, date, timedelta, timezone
from difflib import SequenceMatcher
from sqlalchemy import func
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
    Matches lost and found reports created within 60 days.
    """

    def run_matching(self, report_id, report_type):
        """
        Run the matching engine for a newly submitted report.
        Returns a list of Match instances created/updated.
        """
        logger.info(f"Running AI matching engine for {report_type} report #{report_id}")
        
        if report_type == 'lost':
            return self._match_lost_item(report_id)
        else:
            return self._match_found_item(report_id)

    def _match_lost_item(self, lost_id):
        lost_item = LostItem.query.get(lost_id)
        if not lost_item or lost_item.status == 'Cancelled':
            return []

        # Extend cutoff to 365 days to catch items from months ago
        cutoff_date = datetime.utcnow() - timedelta(days=365)
        lost_cat = (lost_item.category or '').strip().lower()

        candidates = FoundItem.query.filter(
            FoundItem.status != 'Cancelled'
        ).all()

        matches = []
        for found_item in candidates:
            found_cat = (found_item.category or '').strip().lower()
            # Allow all items to be matched — category difference just lowers score
            # Only skip if both are completely different and neither is 'other'
            # (scoring algorithm handles category relevance)
            m = self._compute_and_save_match(lost_item, found_item)
            if m:
                matches.append(m)

        return matches

    def _match_found_item(self, found_id):
        found_item = FoundItem.query.get(found_id)
        if not found_item or found_item.status == 'Cancelled':
            return []

        # Extend cutoff to 365 days to catch items from months ago
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=365)
        found_cat = (found_item.category or '').strip().lower()

        candidates = LostItem.query.filter(
            LostItem.status != 'Cancelled',
            LostItem.created_at >= cutoff_date
        ).all()

        matches = []
        for lost_item in candidates:
            # Allow all items to be matched — scoring handles relevance
            m = self._compute_and_save_match(lost_item, found_item)
            if m:
                matches.append(m)

        return matches

    def _compute_and_save_match(self, lost, found):
        # 0. Category match boost (not in weighted total but used for filtering)
        lost_cat = (lost.category or '').strip().lower()
        found_cat = (found.category or '').strip().lower()
        cat_match = (lost_cat == found_cat or lost_cat in found_cat or found_cat in lost_cat
                     or not lost_cat or not found_cat or lost_cat == 'other' or found_cat == 'other')

        # 1. Item Name / Title Similarity (25%)
        title_score = self._str_sim(lost.item_name, found.item_name)


        # 2. Image similarity (20%)
        has_images = lost.image_path is not None and found.image_path is not None
        image_score = 0.5
        if has_images:
            if lost.image_path == found.image_path:
                image_score = 1.0
            elif lost.color.lower() in found.description.lower() or found.color.lower() in lost.description.lower():
                image_score = 0.85
            else:
                image_score = 0.65
        else:
            image_score = title_score

        # 3. Brand & Model (15%)
        lost_brand = (lost.additional_details.get('brand', '') if lost.additional_details else '').strip().lower()
        lost_model = (lost.additional_details.get('model', '') if lost.additional_details else '').strip().lower()
        found_brand = (found.additional_details.get('brand', '') if found.additional_details else '').strip().lower()
        found_model = (found.additional_details.get('model', '') if found.additional_details else '').strip().lower()
        
        brand_sim = self._str_sim(lost_brand, found_brand)
        model_sim = self._str_sim(lost_model, found_model)
        brand_score = (brand_sim + model_sim) / 2.0

        # 4. Description (15%)
        desc_score = self._str_sim(lost.description, found.description)

        # 5. Color (15%)
        color_score = 0.0
        lost_col = (lost.color or '').strip().lower()
        found_col = (found.color or '').strip().lower()
        if lost_col == found_col:
            color_score = 1.0
        elif lost_col in found_col or found_col in lost_col:
            color_score = 0.8
        else:
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
                color_score = 0.2

        # 6. Location + Date + Time (10%)
        lost_loc = (lost.location or '').lower()
        found_loc = (found.location or '').lower()
        loc_score = 1.0 if lost_loc == found_loc or lost_loc in found_loc or found_loc in lost_loc else 0.4

        # Handle date as string or date object
        try:
            from datetime import date as date_type
            ld = lost.date if isinstance(lost.date, date_type) else date_type.fromisoformat(str(lost.date))
            fd = found.date if isinstance(found.date, date_type) else date_type.fromisoformat(str(found.date))
            days_diff = abs((fd - ld).days)
        except Exception:
            days_diff = 1
        date_score = 1.0 if days_diff == 0 else (0.9 if days_diff <= 1 else (0.7 if days_diff <= 3 else (0.5 if days_diff <= 7 else 0.2)))

        time_score = 0.5
        try:
            from datetime import time as time_type
            def _parse_time(t):
                if t is None: return None
                if isinstance(t, time_type): return t
                parts = str(t).split(':')
                return time_type(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
            lt = _parse_time(lost.time)
            ft = _parse_time(found.time)
            if lt and ft:
                t1 = lt.hour * 60 + lt.minute
                t2 = ft.hour * 60 + ft.minute
                min_diff = abs(t1 - t2)
                if min_diff <= 60: time_score = 1.0
                elif min_diff <= 180: time_score = 0.7
                else: time_score = 0.4
        except Exception:
            time_score = 0.5
            
        location_score = (loc_score + date_score + time_score) / 3.0

        # Question Answers (Bonus boost)
        lost_qas = QuestionAnswer.query.filter_by(report_type='lost', report_id=lost.report_id).all()
        found_qas = QuestionAnswer.query.filter_by(report_type='found', report_id=found.report_id).all()
        qa_score = 0.5
        if lost_qas and found_qas:
            match_qa = 0
            total_qa = len(lost_qas)
            for l_qa in lost_qas:
                for f_qa in found_qas:
                    if l_qa.question.strip().lower() == f_qa.question.strip().lower():
                        if self._str_sim(l_qa.answer, f_qa.answer) >= 0.7:
                            match_qa += 1
            qa_score = (match_qa / total_qa) if total_qa > 0 else 0.5

        # Weighted calculation (sum = 100%)
        overall = (title_score * 25.0 + 
                   image_score * 20.0 + 
                   brand_score * 15.0 + 
                   desc_score * 15.0 + 
                   color_score * 15.0 + 
                   location_score * 10.0)

        # Category match bonus/penalty
        if cat_match:
            overall = min(overall + 5.0, 100.0)  # same category boosts confidence
        else:
            overall = max(overall - 10.0, 0.0)   # different category lowers confidence

        if title_score >= 0.8 and color_score >= 0.7 and loc_score >= 0.7:
            overall = max(overall, 85.0)

        overall = round(overall, 1)

        # Ignore very weak matches below 30%
        if overall < 30.0:
            return None


        # Check if match already exists
        existing_match = Match.query.filter_by(
            lost_report_id=lost.report_id,
            found_report_id=found.report_id
        ).first()

        match_record = existing_match
        if existing_match:
            if overall > existing_match.overall_score:
                existing_match.image_score = round(image_score * 100, 1)
                existing_match.brand_score = round(brand_score * 100, 1)
                existing_match.description_score = round(desc_score * 100, 1)
                existing_match.color_score = round(color_score * 100, 1)
                existing_match.location_score = round(location_score * 100, 1)
                existing_match.question_score = round(qa_score * 100, 1)
                existing_match.overall_score = overall
                db.session.commit()
        else:
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
            db.session.flush()
            match_record = new_match

        # Update status if confidence >= 60%
        if overall >= 60.0:
            if lost.status == 'Searching':
                lost.status = 'Matched'
            if found.status == 'Searching':
                found.status = 'Matched'

            # 1. Notify Lost Item Owner (User A)
            lost_notif_title = f"🎉 Your Lost Item May Have Been Found! ({overall}% match)"
            lost_notif_msg = (
                f"Great news! Someone found an item matching your lost '{lost.item_name}'. "
                f"It was found at '{found.location}' on {found.date.strftime('%d %b %Y')}. "
                f"AI Confidence Score: {overall}%. Go to Match Alerts to view details."
            )
            existing_l_notif = Notification.query.filter_by(
                student_id=lost.student_id,
                title=lost_notif_title
            ).first()
            if not existing_l_notif:
                db.session.add(Notification(
                    student_id=lost.student_id,
                    title=lost_notif_title,
                    message=lost_notif_msg
                ))

            # 2. Notify Found Item Finder (User B)
            found_notif_title = f"🎯 Item Match Alert for Found '{found.item_name}' ({overall}% match)"
            found_notif_msg = (
                f"Your reported found item '{found.item_name}' matches a lost report for '{lost.item_name}'! "
                f"AI Confidence Score: {overall}%. Check your Match Alerts for details."
            )
            existing_f_notif = Notification.query.filter_by(
                student_id=found.student_id,
                title=found_notif_title
            ).first()
            if not existing_f_notif:
                db.session.add(Notification(
                    student_id=found.student_id,
                    title=found_notif_title,
                    message=found_notif_msg
                ))

        db.session.commit()

        # Send match email notifications for BOTH users (for overall >= 50%)
        if overall >= 50.0:
            try:
                from app.models.student import Student
                from app.services.email_service import send_match_found_email
                
                # Email 1: Lost item owner
                lost_student = Student.query.get(lost.student_id)
                if lost_student:
                    send_match_found_email(lost_student, lost, found, overall, recipient_type='lost')
                
                # Email 2: Found item finder
                if found.student_id != lost.student_id:
                    found_student = Student.query.get(found.student_id)
                    if found_student:
                        send_match_found_email(found_student, lost, found, overall, recipient_type='found')
            except Exception as e:
                logger.warning(f"Failed to send match emails: {e}")

        logger.info(f"Match stored: Lost#{lost.report_id} ↔ Found#{found.report_id} | Score: {overall}%")
        return match_record

    def _str_sim(self, s1, s2):
        """Hybrid similarity: sequence match + token set overlap."""
        if not s1 or not s2:
            return 0.5
        a, b = s1.lower().strip(), s2.lower().strip()
        if a == b:
            return 1.0
        seq_ratio = SequenceMatcher(None, a, b).ratio()
        tokens_a = set(a.split())
        tokens_b = set(b.split())
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
        return round((seq_ratio * 0.4 + jaccard * 0.6), 4)

matching_service = MatchingService()
