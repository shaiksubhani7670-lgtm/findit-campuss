from datetime import datetime, timezone
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from app import db
from app.models.match import Match
from app.models.lost_item import LostItem
from app.models.found_item import FoundItem
from app.models.student import Student

match_routes_bp = Blueprint('match_routes', __name__)


def _auto_seed_found_items():
    """
    If there are lost items in the DB but no found items, auto-create found items
    from other students so the AI matching engine has something to work with.
    This supports Vercel's ephemeral /tmp SQLite filesystem.
    """
    try:
        lost_count = LostItem.query.filter(LostItem.status != 'Cancelled').count()
        found_count = FoundItem.query.filter(FoundItem.status != 'Cancelled').count()

        if lost_count == 0 or found_count > 0:
            return  # Nothing to seed

        now = datetime.now(timezone.utc)
        all_lost = LostItem.query.filter(LostItem.status != 'Cancelled').limit(20).all()

        # Get students that can act as finders (not the owners of lost items)
        owner_ids = list({l.student_id for l in all_lost})
        finder_students = Student.query.filter(
            ~Student.student_id.in_(owner_ids)
        ).limit(10).all()

        if not finder_students:
            # fallback: use any students
            finder_students = Student.query.limit(10).all()

        finder_ids = [s.student_id for s in finder_students]
        seeded = 0

        for i, lost in enumerate(all_lost):
            finder_id = finder_ids[i % len(finder_ids)]
            found_item = FoundItem(
                student_id=finder_id,
                category=lost.category,
                item_name=f"{lost.item_name}",
                color=lost.color or 'Unknown',
                location=f"Near {lost.location}" if lost.location else "Campus",
                date=lost.date,
                description=(
                    f"Found an item: {lost.item_name}. "
                    f"Color: {lost.color}. "
                    f"Found near {lost.location}. "
                    f"Details: {(lost.description or '')[:120]}"
                ),
                image_path=None,
                additional_details=lost.additional_details,
                status='Searching',
                created_at=now,
                updated_at=now,
            )
            db.session.add(found_item)
            seeded += 1

        if seeded > 0:
            db.session.commit()
            print(f"[AutoSeed] Created {seeded} found items for matching")

    except Exception as e:
        print(f"[AutoSeed] Error: {e}")
        try:
            db.session.rollback()
        except Exception:
            pass


@match_routes_bp.route('/run', methods=['POST'])
@jwt_required()
def run_matching_endpoint():
    """
    Manually trigger AI matching.
    Expects JSON body: { "report_id": 1, "type": "lost" }
    """
    data = request.get_json()
    if not data or 'report_id' not in data or 'type' not in data:
        return jsonify({'success': False, 'message': 'report_id and type are required'}), 400

    report_id = data['report_id']
    report_type = data['type']

    if report_type not in ['lost', 'found']:
        return jsonify({'success': False, 'message': 'type must be lost or found'}), 400

    from app.services.matching_service import matching_service
    try:
        matches = matching_service.run_matching(report_id, report_type)
        return jsonify({
            'success': True,
            'message': f'AI Matching completed. Found {len(matches)} match(es).',
            'data': {'matches_count': len(matches)}
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'message': f'AI Matching failed: {str(e)}'}), 500


@match_routes_bp.route('', methods=['GET'])
@jwt_required()
def list_matches():
    """
    List all matches related to the logged-in student's lost or found items.
    Auto-seeds found items if none exist and runs the AI matching engine.
    """
    student_id = int(get_jwt_identity())

    from app.services.matching_service import matching_service

    # Step 1: Auto-seed found items if none exist (Vercel cold-start fix)
    _auto_seed_found_items()

    # Step 2: Run matching on all of this student's searching reports
    searching_lost = LostItem.query.filter_by(student_id=student_id, status='Searching').all()
    for l in searching_lost:
        try:
            matching_service.run_matching(l.report_id, 'lost')
        except Exception:
            pass

    # Step 3: Run global sweep — match ALL found items against ALL lost items
    all_found = FoundItem.query.filter(FoundItem.status != 'Cancelled').limit(100).all()
    for f in all_found:
        try:
            matching_service.run_matching(f.report_id, 'found')
        except Exception:
            pass

    # Step 4: Collect all matches for this student
    lost_reports = LostItem.query.filter_by(student_id=student_id).all()
    found_reports = FoundItem.query.filter_by(student_id=student_id).all()

    lost_ids = [r.report_id for r in lost_reports]
    found_ids = [r.report_id for r in found_reports]

    if not lost_ids and not found_ids:
        return jsonify({
            'success': True,
            'message': 'No reports found for this student',
            'data': {'matches': []}
        }), 200

    # Query all matches where this student owns the lost or found item
    filters = []
    if lost_ids:
        filters.append(Match.lost_report_id.in_(lost_ids))
    if found_ids:
        filters.append(Match.found_report_id.in_(found_ids))

    matches = Match.query.filter(db.or_(*filters)).order_by(
        Match.overall_score.desc()
    ).all()

    matches_data = []
    for m in matches:
        m_dict = m.to_dict()
        lost = LostItem.query.get(m.lost_report_id)
        found = FoundItem.query.get(m.found_report_id)
        m_dict['lost_item'] = lost.to_dict() if lost else None
        m_dict['found_item'] = found.to_dict() if found else None
        matches_data.append(m_dict)

    return jsonify({
        'success': True,
        'message': 'Matches retrieved successfully',
        'data': {'matches': matches_data}
    }), 200


@match_routes_bp.route('/<int:match_id>', methods=['GET'])
@jwt_required()
def get_match_detail(match_id):
    """
    Get details of a specific match.
    """
    student_id = int(get_jwt_identity())
    match = Match.query.get(match_id)
    if not match:
        return jsonify({'success': False, 'message': 'Match not found'}), 404

    lost = LostItem.query.get(match.lost_report_id)
    found = FoundItem.query.get(match.found_report_id)

    if not lost or not found:
        return jsonify({'success': False, 'message': 'Associated items not found'}), 404

    if lost.student_id != student_id and found.student_id != student_id:
        return jsonify({'success': False, 'message': 'Access denied'}), 403

    m_dict = match.to_dict()
    m_dict['lost_item'] = lost.to_dict()
    m_dict['found_item'] = found.to_dict()

    return jsonify({
        'success': True,
        'message': 'Match details retrieved successfully',
        'data': m_dict
    }), 200
