using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Caching.Distributed;
using Microsoft.Extensions.Caching.Memory;
using Patient_Management_System.Data;
using Patient_Management_System.Exceptions;
using Patient_Management_System.Kafka;
using Patient_Management_System.Models;

namespace Patient_Management_System.Services
{
    public static class KafkaTopics
    {
        public const string PatientUpdatedTopic = "PatientUpdatedTopic";
    }

    public class PatientService(AppDbContext context, IMemoryCache memoryCache, IDistributedCache redisCache, KafkaProducer kafkaProducer, ILogger<PatientService> logger, IConfiguration config, RedisService redis, ContextService contextService) : IPatientService
    {
        private readonly AppDbContext _context = context;

        private readonly IMemoryCache _memoryCache = memoryCache;

        private readonly IDistributedCache _redisCache = redisCache;

        private readonly KafkaProducer _kafkaProducer = kafkaProducer;

        private readonly IConfiguration _config = config;

        private readonly ILogger<PatientService> _logger = logger;

        private readonly RedisService _redis = redis;

        private readonly ContextService _contextService = contextService;

        public async Task<IEnumerable<Patient>> GetPatientsAsync(string search, string sortCol, string sortDir, int pageNo, int pageSize)
        {
            return await _context.Patients
                    .FromSqlInterpolated($"SELECT * FROM GetPatientsSP({search}, {sortCol}, {sortDir}, {pageNo}, {pageSize})")
                    .ToListAsync();
        }

        public async Task<Patient> GetPatientByIdAsync(int id)
        {
            string cacheKey = $"Patient_{id}";

            // Try Memory Cache
            _logger.LogInformation("Trying to get patient with ID {PatientId} from Memory Cache...", id);
            if(_memoryCache.TryGetValue(cacheKey, out Patient cachedPatient))
            {
                _logger.LogInformation("Patient with ID {PatientId} found in Memory Cache.", id);
                return cachedPatient;
            }

            // If Memory Cache miss, try Redis Cache
            _logger.LogInformation("Memory Cache miss. Trying to get patient with ID {PatientId} from Redis Cache...", id);
            var patient = await _redisCache.GetStringAsync(cacheKey);
            if(patient != null)
            {
                _logger.LogInformation("Patient with ID {PatientId} found in Redis Cache.", id);
                _logger.LogInformation("Storing patient with ID {PatientId} in Memory Cache...", id);
                var patientObj = JsonSerializer.Deserialize<Patient>(patient);
                _memoryCache.Set(
                    cacheKey,
                    patientObj,
                    new MemoryCacheEntryOptions
                    {
                        AbsoluteExpirationRelativeToNow = TimeSpan.FromMinutes(5),
                        SlidingExpiration = TimeSpan.FromMinutes(2)
                    });
                _logger.LogInformation("Patient with ID {PatientId} stored in Memory Cache.", id);
                return patientObj;
            }

            // If both caches miss, fetch from DB
            _logger.LogInformation("Redis Cache miss. Fetching patient with ID {PatientId} from Database...", id);
            var patientById = await _context.Patients.FindAsync(id) ?? throw new PatientNotFoundException(id);

            // Store in both caches
            _logger.LogInformation("Found patient with ID {PatientId} in Database. Caching now...", id);
            _memoryCache.Set(
                cacheKey,
                patientById,
                new MemoryCacheEntryOptions
                {
                    AbsoluteExpirationRelativeToNow = TimeSpan.FromMinutes(5),
                    SlidingExpiration = TimeSpan.FromMinutes(2)
                });
            await _redisCache.SetStringAsync(cacheKey, JsonSerializer.Serialize(patientById),
                new DistributedCacheEntryOptions
                {
                    AbsoluteExpirationRelativeToNow = TimeSpan.FromMinutes(10),
                    SlidingExpiration = TimeSpan.FromMinutes(5)
                });

            _logger.LogInformation("Patient with ID {PatientId} stored in both Redis and Memory Cache.", id);
            return patientById;
        }

        public async Task<Patient> CreatePatientAsync(Patient patient)
        {
            if(patient == null || string.IsNullOrWhiteSpace(patient.Name) || string.IsNullOrWhiteSpace(patient.Address) || patient.DateOfBirth == default || patient.DateOfBirth >= DateOnly.FromDateTime(DateTime.Today) || patient.RegisteredDate == default || patient.RegisteredDate < patient.DateOfBirth)
            {
                throw new ArgumentException("Invalid patient details!!!");
            }

            var patientByEmail = await _context.Patients.FirstOrDefaultAsync(p => p.Email.ToLower() == patient.Email.ToLower());
            if(patientByEmail != null)
            {
                throw new DuplicateEmailException(patient.Email);
            }

            var newPatient = new Patient
            {
                Name = patient.Name,
                Email = patient.Email,
                Address = patient.Address,
                DateOfBirth = patient.DateOfBirth,
                RegisteredDate = patient.RegisteredDate
            };

            _context.Patients.Add(newPatient);
            await _context.SaveChangesAsync();
            await _kafkaProducer.PublishAsync(_config["Kafka:PatientCreatedTopic"], new { PatientId = newPatient.Id });
            return newPatient;
        }

        public async Task<Patient> UpdatePatientAsync(int id, Patient patient)
        {
            var existingPatient = await _context.Patients.FindAsync(id) ?? throw new PatientNotFoundException(id);

            if(patient == null || string.IsNullOrWhiteSpace(patient.Name) || string.IsNullOrWhiteSpace(patient.Address) || patient.DateOfBirth == default || patient.DateOfBirth >= DateOnly.FromDateTime(DateTime.Today) || patient.RegisteredDate == default || patient.RegisteredDate < patient.DateOfBirth)
            {
                throw new ArgumentException("Invalid patient details!!!");
            }

            var patientByEmail = await _context.Patients.FirstOrDefaultAsync(p => p.Email.ToLower() == patient.Email.ToLower() && p.Id != id);
            if(patientByEmail != null)
            {
                throw new DuplicateEmailException(patient.Email);
            }

            existingPatient.Name = patient.Name;
            existingPatient.Email = patient.Email;
            existingPatient.Address = patient.Address;
            existingPatient.DateOfBirth = patient.DateOfBirth;
            existingPatient.RegisteredDate = patient.RegisteredDate;

            await _context.SaveChangesAsync();
            await _kafkaProducer.PublishAsync(_config["Kafka:PatientUpdatedTopic"], new { PatientId = id });

            // Invalidate caches
            _memoryCache.Remove($"Patient_{id}");
            await _redisCache.RemoveAsync($"Patient_{id}");

            return existingPatient;
        }

        public async Task DeletePatientAsync(int id)
        {
            var existingPatient = await _context.Patients.FindAsync(id) ?? throw new PatientNotFoundException(id);
            _context.Patients.Remove(existingPatient);
            await _context.SaveChangesAsync();

            await _kafkaProducer.PublishAsync(_config["Kafka:PatientDeletedTopic"], new { PatientId = id });

            // Invalidate caches
            _memoryCache.Remove($"Patient_{id}");
            await _redisCache.RemoveAsync($"Patient_{id}");
        }
    }
}
