using Patient_Management_System.Models;
using Patient_Management_System.Data;
using Patient_Management_System.Kafka;

namespace Patient_Management_System.Services
{
    public class BillingAccountService(AppDbContext context, KafkaProducer kafkaProducer, IConfiguration config)
    {
        private readonly AppDbContext _context = context;

        private readonly KafkaProducer _kafkaProducer = kafkaProducer;

        private readonly IConfiguration _config = config;

        public async Task<Billing> CreateAccountAsync(int patientId)
        {
            var billing = new Billing
            {
                PatientId = patientId,
                AccountId = Guid.NewGuid().ToString(),
                Status = "ACTIVE"
            };

            _context.Billings.Add(billing);
            await _context.SaveChangesAsync();
            await _kafkaProducer.PublishAsync(_config["Kafka:BillingCreatedTopic"], new { PatientId = patientId });
            return billing;
        }
    }
}