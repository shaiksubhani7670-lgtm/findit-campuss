from datetime import datetime, timezone
from app import db

class Match(db.Model):
    """
    Match model representing comparison results between lost and found items.
    """
    __tablename__ = 'matches'

    match_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    lost_report_id = db.Column(db.Integer, db.ForeignKey('lost_items.report_id', ondelete='CASCADE'), nullable=False)
    found_report_id = db.Column(db.Integer, db.ForeignKey('found_items.report_id', ondelete='CASCADE'), nullable=False)
    image_score = db.Column(db.Float, default=0.0, nullable=False)
    brand_score = db.Column(db.Float, default=0.0, nullable=False)
    description_score = db.Column(db.Float, default=0.0, nullable=False)
    color_score = db.Column(db.Float, default=0.0, nullable=False)
    location_score = db.Column(db.Float, default=0.0, nullable=False)
    question_score = db.Column(db.Float, default=0.0, nullable=False)
    overall_score = db.Column(db.Float, default=0.0, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    claims = db.relationship('Claim', backref='match', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def id(self):
        """Alias for compatibility with existing code."""
        return self.match_id

    @property
    def brand_model_score(self):
        """Alias for brand_score."""
        return self.brand_score

    def to_dict(self):
        """Serialize match details."""
        return {
            'match_id': self.match_id,
            'id': self.match_id,
            'lost_report_id': self.lost_report_id,
            'found_report_id': self.found_report_id,
            'image_score': self.image_score,
            'brand_score': self.brand_score,
            'brand_model_score': self.brand_score,
            'description_score': self.description_score,
            'color_score': self.color_score,
            'location_score': self.location_score,
            'question_score': self.question_score,
            'overall_score': self.overall_score,
            'created_at': self.created_at.isoformat()
        }

    def __repr__(self):
        return f'<Match {self.match_id}: Lost#{self.lost_report_id} ↔ Found#{self.found_report_id} ({self.overall_score}%)>'
